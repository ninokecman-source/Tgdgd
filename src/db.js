import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite'; // ugrađeno u Node.js 22.13+

// Statusi podsjetnika:
//   sending  – zauzeto, slanje u tijeku
//   sent     – WhatsApp prihvatio poruku (dalje prati "delivery")
//   failed   – slanje nije uspjelo (error_code) – ponovit će se u sljedećem krugu
//   skipped_no_phone / skipped_no_consent – nije poslano, recepcija može nazvati
const DONE = new Set(['sending', 'sent']);
const RANK = { sent: 1, delivered: 2, read: 3 };
const NOW = "strftime('%Y-%m-%dT%H:%M:%SZ','now')";

export function openDb(dbPath) {
  if (dbPath !== ':memory:') fs.mkdirSync(path.dirname(path.resolve(dbPath)), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec(`
    PRAGMA journal_mode = WAL;
    PRAGMA busy_timeout = 5000;
    CREATE TABLE IF NOT EXISTS reminders (
      id              INTEGER PRIMARY KEY,
      reminder_key    TEXT NOT NULL UNIQUE,   -- pacijent|početak termina
      patient_id      TEXT NOT NULL,
      patient_name    TEXT,
      phone           TEXT,
      starts_at       TEXT NOT NULL,          -- UTC ISO
      local_date      TEXT NOT NULL,          -- YYYY-MM-DD (Europe/Zagreb)
      appointments    TEXT NOT NULL,          -- JSON [{kind,id,attendeeId}]
      status          TEXT NOT NULL,
      attempts        INTEGER NOT NULL DEFAULT 0,
      wamid           TEXT UNIQUE,
      delivery        TEXT,                   -- sent / delivered / read / failed
      error_code      TEXT,
      error_message   TEXT,
      reply           TEXT,                   -- confirmed / change_requested / other
      reply_text      TEXT,
      reply_at        TEXT,
      created_at      TEXT NOT NULL DEFAULT (${NOW}),
      updated_at      TEXT NOT NULL DEFAULT (${NOW})
    );
    CREATE INDEX IF NOT EXISTS idx_rem_date ON reminders(local_date);
    CREATE INDEX IF NOT EXISTS idx_rem_phone ON reminders(phone);
    CREATE TABLE IF NOT EXISTS inbound (
      wamid       TEXT PRIMARY KEY,           -- ID dolazne poruke (idempotentnost webhooka)
      phone       TEXT,
      created_at  TEXT NOT NULL DEFAULT (${NOW})
    );
  `);

  const q = {
    get: db.prepare('SELECT * FROM reminders WHERE reminder_key = ?'),
    insert: db.prepare(`INSERT INTO reminders
      (reminder_key, patient_id, patient_name, phone, starts_at, local_date, appointments, status, attempts)
      VALUES (:reminder_key, :patient_id, :patient_name, :phone, :starts_at, :local_date, :appointments, :status, :attempts)`),
    reset: db.prepare(`UPDATE reminders SET patient_name=:patient_name, phone=:phone, appointments=:appointments,
      status=:status, attempts=attempts + :attempts, error_code=NULL, error_message=NULL, updated_at=${NOW}
      WHERE reminder_key=:reminder_key`),
    sent: db.prepare(`UPDATE reminders SET status='sent', wamid=?, delivery='sent', updated_at=${NOW} WHERE reminder_key=?`),
    failed: db.prepare(`UPDATE reminders SET status='failed', error_code=?, error_message=?, updated_at=${NOW} WHERE reminder_key=?`),
    byWamid: db.prepare('SELECT * FROM reminders WHERE wamid = ?'),
    latestForPhone: db.prepare(`SELECT * FROM reminders WHERE phone = ? AND status='sent' AND created_at >= ?
      ORDER BY created_at DESC LIMIT 1`),
    delivery: db.prepare(`UPDATE reminders SET delivery=?, error_code=COALESCE(?, error_code),
      error_message=COALESCE(?, error_message), updated_at=${NOW} WHERE wamid=?`),
    reply: db.prepare(`UPDATE reminders SET reply=?, reply_text=?, reply_at=${NOW}, updated_at=${NOW} WHERE id=?`),
    inboundInsert: db.prepare('INSERT OR IGNORE INTO inbound (wamid, phone) VALUES (?, ?)'),
    forDates: db.prepare('SELECT * FROM reminders WHERE local_date IN (SELECT value FROM json_each(?)) ORDER BY starts_at, patient_name'),
    purgeRem: db.prepare('DELETE FROM reminders WHERE created_at < ?'),
    purgeIn: db.prepare('DELETE FROM inbound WHERE created_at < ?'),
  };

  const tx = (fn) => (...args) => {
    db.exec('BEGIN IMMEDIATE');
    try {
      const r = fn(...args);
      db.exec('COMMIT');
      return r;
    } catch (e) {
      db.exec('ROLLBACK');
      throw e;
    }
  };

  const MAX_ATTEMPTS = 3;
  // node:sqlite odbija višak imenovanih parametara – šaljemo samo one koje upit koristi
  const insertRow = (row, status, attempts) => q.insert.run({
    reminder_key: row.reminder_key, patient_id: row.patient_id, patient_name: row.patient_name ?? null,
    phone: row.phone ?? null, starts_at: row.starts_at, local_date: row.local_date, appointments: row.appointments, status, attempts,
  });
  const resetRow = (row, status, attempts) => q.reset.run({
    reminder_key: row.reminder_key, patient_name: row.patient_name ?? null, phone: row.phone ?? null,
    appointments: row.appointments, status, attempts,
  });

  return {
    raw: db,

    /**
     * Atomski "zauzme" podsjetnik za slanje. Vraća true ako ga treba poslati.
     * Ne šalje ponovno ako je već poslan, ako se upravo šalje, ili ako je
     * već 3 puta neuspješno pokušan (trajna greška – recepcija vidi na /status).
     */
    claim: tx((row) => {
      const existing = q.get.get(row.reminder_key);
      if (!existing) {
        insertRow(row, 'sending', 1);
        return true;
      }
      if (DONE.has(existing.status)) return false;
      if (existing.status === 'failed' && existing.attempts >= MAX_ATTEMPTS) return false;
      resetRow(row, 'sending', 1);
      return true;
    }),

    /** Zapis preskočenog podsjetnika (bez mobitela / bez privole). */
    markSkipped: tx((row, status) => {
      const existing = q.get.get(row.reminder_key);
      if (!existing) insertRow(row, status, 0);
      else if (!DONE.has(existing.status) && existing.status !== 'failed') resetRow(row, status, 0);
    }),

    markSent: (key, wamid) => q.sent.run(wamid, key),
    markFailed: (key, code, msg) => q.failed.run(String(code), String(msg).slice(0, 500), key),
    get: (key) => q.get.get(key),
    byWamid: (wamid) => q.byWamid.get(wamid),
    latestForPhone: (phone, sinceIso) => q.latestForPhone.get(phone, sinceIso),

    /** Status isporuke; nikad ne "spušta" read -> delivered. failed je konačan. */
    updateDelivery(wamid, status, errCode, errMsg) {
      const row = q.byWamid.get(wamid);
      if (!row || row.delivery === 'failed') return false;
      if (status !== 'failed' && (RANK[status] || 0) <= (RANK[row.delivery] || 0)) return false;
      q.delivery.run(status, errCode == null ? null : String(errCode), errMsg ?? null, wamid);
      return true;
    },

    setReply: (id, reply, text) => q.reply.run(reply, text ?? null, id),
    /** true ako je dolazna poruka nova (Meta zna isti webhook poslati više puta). */
    recordInbound: (wamid, phone) => q.inboundInsert.run(wamid, phone ?? null).changes === 1,
    forDates: (dates) => q.forDates.all(JSON.stringify(dates)),
    purgeOlderThan: (iso) => q.purgeRem.run(iso).changes + q.purgeIn.run(iso).changes,
    close: () => db.close(),
  };
}
