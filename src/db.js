"use strict";
// SQLite baza (poglavlje 3). Sva vremena su UTC ISO nizovi (G-80).
// Server (webhook) i posao podsjetnika pišu u istu datoteku, pa je uključen
// WAL način i čekanje na zaključanu bazu.

const fs = require("node:fs");
const path = require("node:path");
const Database = require("better-sqlite3");

const SCHEMA = `
CREATE TABLE IF NOT EXISTS wa_messages (
  id              INTEGER PRIMARY KEY,
  wamid           TEXT UNIQUE,                 -- ID poruke od Mete
  appointment_id  TEXT,
  patient_phone   TEXT NOT NULL,               -- E.164 bez '+', npr. 385912345678
  direction       TEXT NOT NULL CHECK (direction IN ('out', 'in')),
  type            TEXT NOT NULL,               -- template | text | button | image ...
  status          TEXT,                        -- out: accepted/sent/delivered/read/failed; in: received
  error_code      INTEGER,
  body            TEXT,                        -- samo dolazni tekst pacijenta, za inbox recepcije
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS wa_messages_phone ON wa_messages (patient_phone, direction, created_at);

CREATE TABLE IF NOT EXISTS whatsapp_consent (
  phone             TEXT PRIMARY KEY,
  patient_id        TEXT,
  consent_given_at  TEXT NOT NULL,
  consent_source    TEXT NOT NULL,
  revoked_at        TEXT
);

-- Jedan redak po terminu. Ako se termin pomakne, novo vrijeme je novi ključ,
-- pa pacijent dobije podsjetnik za novo vrijeme.
CREATE TABLE IF NOT EXISTS reminders (
  appointment_id       TEXT NOT NULL,
  starts_at            TEXT NOT NULL,
  patient_id           TEXT,
  patient_name         TEXT,
  patient_phone        TEXT,
  status               TEXT NOT NULL,   -- pending | sending | sent | failed | skipped | unknown
  wamid                TEXT,
  attempts             INTEGER NOT NULL DEFAULT 0,
  last_error_code      INTEGER,
  note                 TEXT,
  reply                TEXT,            -- confirmed | change_requested
  replied_at           TEXT,
  undelivered_alerted  INTEGER NOT NULL DEFAULT 0,
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL,
  PRIMARY KEY (appointment_id, starts_at)
);
CREATE INDEX IF NOT EXISTS reminders_wamid ON reminders (wamid);

-- Sirovi webhook događaji: spremaju se prije odgovora 200, obrađuju odmah
-- nakon toga. Ako server padne usred obrade, ništa se ne gubi.
CREATE TABLE IF NOT EXISTS webhook_events (
  id            INTEGER PRIMARY KEY,
  received_at   TEXT NOT NULL,
  payload       TEXT NOT NULL,
  processed_at  TEXT,
  error         TEXT
);

-- Zadaci za recepciju: nazvati pacijenta, pročitati poruku, provjeriti slanje.
CREATE TABLE IF NOT EXISTS tasks (
  id              INTEGER PRIMARY KEY,
  kind            TEXT NOT NULL,
  appointment_id  TEXT,
  patient_phone   TEXT,
  message_id      INTEGER,
  details         TEXT,
  created_at      TEXT NOT NULL,
  done_at         TEXT
);

CREATE TABLE IF NOT EXISTS job_runs (
  id           INTEGER PRIMARY KEY,
  job          TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  planned      INTEGER,
  sent         INTEGER,
  failed       INTEGER,
  error        TEXT
);

CREATE TABLE IF NOT EXISTS kv (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
`;

const STATUS_RANK = { accepted: 0, sent: 1, delivered: 2, read: 3 };

class Store {
  constructor(dbPath) {
    if (dbPath !== ":memory:") fs.mkdirSync(path.dirname(dbPath), { recursive: true });
    this.db = new Database(dbPath);
    this.db.pragma("journal_mode = WAL");
    this.db.pragma("busy_timeout = 10000");
    this.db.exec(SCHEMA);
  }

  close() {
    this.db.close();
  }

  // ---- privole ---------------------------------------------------------

  hasConsent(phone) {
    return Boolean(
      this.db.prepare("SELECT 1 FROM whatsapp_consent WHERE phone = ? AND revoked_at IS NULL").get(phone)
    );
  }

  addConsent({ phone, patientId = null, source, givenAt }) {
    this.db
      .prepare(
        `INSERT INTO whatsapp_consent (phone, patient_id, consent_given_at, consent_source, revoked_at)
         VALUES (?, ?, ?, ?, NULL)
         ON CONFLICT (phone) DO UPDATE SET
           patient_id = COALESCE(excluded.patient_id, whatsapp_consent.patient_id),
           consent_given_at = excluded.consent_given_at,
           consent_source = excluded.consent_source,
           revoked_at = NULL`
      )
      .run(phone, patientId, givenAt, source);
  }

  revokeConsent(phone, at) {
    return (
      this.db
        .prepare("UPDATE whatsapp_consent SET revoked_at = ? WHERE phone = ? AND revoked_at IS NULL")
        .run(at, phone).changes > 0
    );
  }

  listConsents() {
    return this.db.prepare("SELECT * FROM whatsapp_consent ORDER BY consent_given_at DESC").all();
  }

  // ---- podsjetnici -----------------------------------------------------

  getReminder(appointmentId, startsAt) {
    return this.db
      .prepare("SELECT * FROM reminders WHERE appointment_id = ? AND starts_at = ?")
      .get(appointmentId, startsAt);
  }

  // Atomsko zaključavanje (G-82): samo jedan proces može prebaciti termin u
  // 'sending'. Vraća true ako je ovaj proces dobio pravo slanja.
  claimReminder({ appointmentId, startsAt, patientId, patientName, phone, now }) {
    const info = this.db
      .prepare(
        `INSERT INTO reminders (appointment_id, starts_at, patient_id, patient_name, patient_phone,
                                status, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, 'sending', ?, ?)
         ON CONFLICT (appointment_id, starts_at) DO UPDATE SET
           status = 'sending', patient_phone = excluded.patient_phone,
           patient_name = excluded.patient_name, updated_at = excluded.updated_at
         WHERE reminders.status = 'pending'`
      )
      .run(appointmentId, startsAt, patientId, patientName, phone, now, now);
    return info.changes === 1;
  }

  markReminderSent({ appointmentId, startsAt, wamid, phone, now }) {
    this.db.transaction(() => {
      this.db
        .prepare(
          `UPDATE reminders SET status = 'sent', wamid = ?, attempts = attempts + 1, updated_at = ?
           WHERE appointment_id = ? AND starts_at = ?`
        )
        .run(wamid, now, appointmentId, startsAt);
      this.insertOutbound({ wamid, appointmentId, phone, type: "template", createdAt: now });
    })();
  }

  setReminderStatus({ appointmentId, startsAt, status, errorCode = null, note = null, countAttempt = false, now }) {
    this.db
      .prepare(
        `UPDATE reminders SET status = ?, last_error_code = COALESCE(?, last_error_code),
                              note = COALESCE(?, note),
                              attempts = attempts + ?, updated_at = ?
         WHERE appointment_id = ? AND starts_at = ?`
      )
      .run(status, errorCode, note, countAttempt ? 1 : 0, now, appointmentId, startsAt);
  }

  staleSending(beforeIso) {
    return this.db
      .prepare("SELECT * FROM reminders WHERE status = 'sending' AND updated_at < ?")
      .all(beforeIso);
  }

  findReminderByWamid(wamid) {
    return this.db.prepare("SELECT * FROM reminders WHERE wamid = ?").get(wamid);
  }

  setReminderReply({ appointmentId, startsAt, reply, at }) {
    this.db
      .prepare(
        `UPDATE reminders SET reply = ?, replied_at = ?, updated_at = ?
         WHERE appointment_id = ? AND starts_at = ?`
      )
      .run(reply, at, at, appointmentId, startsAt);
  }

  // Poslano, ali do sada nije stiglo "delivered" (G-51).
  undeliveredBefore(nowIso, untilIso) {
    return this.db
      .prepare(
        `SELECT r.* FROM reminders r
         JOIN wa_messages m ON m.wamid = r.wamid
         WHERE r.status = 'sent' AND r.undelivered_alerted = 0
           AND m.status IN ('accepted', 'sent')
           AND r.starts_at > ? AND r.starts_at <= ?`
      )
      .all(nowIso, untilIso);
  }

  markUndeliveredAlerted(appointmentId, startsAt) {
    this.db
      .prepare("UPDATE reminders SET undelivered_alerted = 1 WHERE appointment_id = ? AND starts_at = ?")
      .run(appointmentId, startsAt);
  }

  remindersBetween(fromIso, toIso) {
    return this.db
      .prepare(
        `SELECT r.*, m.status AS delivery_status FROM reminders r
         LEFT JOIN wa_messages m ON m.wamid = r.wamid
         WHERE r.starts_at >= ? AND r.starts_at < ?
         ORDER BY r.starts_at`
      )
      .all(fromIso, toIso);
  }

  // ---- poruke ----------------------------------------------------------

  // Vraća id nove poruke ili null ako je taj wamid već viđen (G-33).
  insertInbound({ wamid, phone, type, body = null, createdAt }) {
    const info = this.db
      .prepare(
        `INSERT OR IGNORE INTO wa_messages (wamid, patient_phone, direction, type, status, body, created_at, updated_at)
         VALUES (?, ?, 'in', ?, 'received', ?, ?, ?)`
      )
      .run(wamid, phone, type, body, createdAt, createdAt);
    return info.changes ? Number(info.lastInsertRowid) : null;
  }

  insertOutbound({ wamid, appointmentId = null, phone, type, createdAt }) {
    this.db
      .prepare(
        `INSERT OR IGNORE INTO wa_messages (wamid, appointment_id, patient_phone, direction, type, status, created_at, updated_at)
         VALUES (?, ?, ?, 'out', ?, 'accepted', ?, ?)`
      )
      .run(wamid, appointmentId, phone, type, createdAt, createdAt);
  }

  getMessage(id) {
    return this.db.prepare("SELECT * FROM wa_messages WHERE id = ?").get(id);
  }

  // G-34: statusi mogu stići obrnutim redom. Nikad se "viši" status ne
  // prepisuje "nižim", a "failed" je konačan.
  applyStatus({ wamid, status, errorCode = null, at }) {
    const row = this.db.prepare("SELECT * FROM wa_messages WHERE wamid = ? AND direction = 'out'").get(wamid);
    if (!row) return { known: false, changed: false };
    if (row.status === "failed") return { known: true, changed: false, row };
    const isUpgrade =
      status === "failed" ||
      (status in STATUS_RANK && STATUS_RANK[status] > (STATUS_RANK[row.status] ?? -1));
    if (!isUpgrade) return { known: true, changed: false, row };
    this.db
      .prepare("UPDATE wa_messages SET status = ?, error_code = COALESCE(?, error_code), updated_at = ? WHERE id = ?")
      .run(status, errorCode, at, row.id);
    return { known: true, changed: true, row: { ...row, status } };
  }

  lastInboundAt(phone) {
    const row = this.db
      .prepare("SELECT MAX(created_at) AS t FROM wa_messages WHERE patient_phone = ? AND direction = 'in'")
      .get(phone);
    return row && row.t ? row.t : null;
  }

  // Poruke koje je API prihvatio, a webhook nije javio ni "sent" (G-31/G-35).
  countUnconfirmedBefore(beforeIso) {
    return this.db
      .prepare("SELECT COUNT(*) AS n FROM wa_messages WHERE direction = 'out' AND status = 'accepted' AND created_at < ?")
      .get(beforeIso).n;
  }

  // ---- zadaci za recepciju ---------------------------------------------

  addTask({ kind, appointmentId = null, phone = null, messageId = null, details = null, createdAt }) {
    return Number(
      this.db
        .prepare(
          `INSERT INTO tasks (kind, appointment_id, patient_phone, message_id, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?)`
        )
        .run(kind, appointmentId, phone, messageId, details, createdAt).lastInsertRowid
    );
  }

  openTasks() {
    return this.db
      .prepare(
        `SELECT t.*, m.body AS message_body, m.type AS message_type
         FROM tasks t LEFT JOIN wa_messages m ON m.id = t.message_id
         WHERE t.done_at IS NULL ORDER BY t.created_at`
      )
      .all();
  }

  completeTask(id, at) {
    return this.db.prepare("UPDATE tasks SET done_at = ? WHERE id = ? AND done_at IS NULL").run(at, id).changes > 0;
  }

  // ---- webhook događaji ------------------------------------------------

  storeEvent(payloadText, receivedAt) {
    const info = this.db
      .prepare("INSERT INTO webhook_events (received_at, payload) VALUES (?, ?)")
      .run(receivedAt, payloadText);
    this.setKv("last_webhook_at", receivedAt);
    return Number(info.lastInsertRowid);
  }

  pendingEvents(limit = 100) {
    return this.db
      .prepare("SELECT * FROM webhook_events WHERE processed_at IS NULL ORDER BY id LIMIT ?")
      .all(limit);
  }

  markEventProcessed(id, at, error = null) {
    this.db.prepare("UPDATE webhook_events SET processed_at = ?, error = ? WHERE id = ?").run(at, error, id);
  }

  // ---- ostalo ----------------------------------------------------------

  getKv(key) {
    const row = this.db.prepare("SELECT value FROM kv WHERE key = ?").get(key);
    return row ? row.value : null;
  }

  setKv(key, value) {
    this.db
      .prepare("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value")
      .run(key, value);
  }

  startJob(job, at) {
    return Number(this.db.prepare("INSERT INTO job_runs (job, started_at) VALUES (?, ?)").run(job, at).lastInsertRowid);
  }

  finishJob(id, { at, planned, sent, failed, error = null }) {
    this.db
      .prepare("UPDATE job_runs SET finished_at = ?, planned = ?, sent = ?, failed = ?, error = ? WHERE id = ?")
      .run(at, planned, sent, failed, error, id);
  }

  lastJobRun(job) {
    return this.db
      .prepare("SELECT * FROM job_runs WHERE job = ? AND finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
      .get(job);
  }

  // Rok čuvanja (poglavlje 5): poruke, podsjetnici i riješeni zadaci stariji
  // od roka se brišu; sirovi webhook događaji već nakon 7 dana.
  purge({ beforeIso, eventsBeforeIso }) {
    return this.db.transaction(() => ({
      messages: this.db.prepare("DELETE FROM wa_messages WHERE created_at < ?").run(beforeIso).changes,
      reminders: this.db.prepare("DELETE FROM reminders WHERE starts_at < ?").run(beforeIso).changes,
      tasks: this.db.prepare("DELETE FROM tasks WHERE done_at IS NOT NULL AND done_at < ?").run(beforeIso).changes,
      events: this.db
        .prepare("DELETE FROM webhook_events WHERE processed_at IS NOT NULL AND received_at < ?")
        .run(eventsBeforeIso).changes,
      jobs: this.db.prepare("DELETE FROM job_runs WHERE started_at < ?").run(beforeIso).changes,
    }))();
  }

  dayReport(fromIso, toIso) {
    const statuses = this.db
      .prepare(
        `SELECT status, COUNT(*) AS n FROM wa_messages
         WHERE direction = 'out' AND type = 'template' AND created_at >= ? AND created_at < ?
         GROUP BY status`
      )
      .all(fromIso, toIso);
    const runs = this.db
      .prepare(
        `SELECT COUNT(*) AS runs, COALESCE(SUM(sent), 0) AS sent, COALESCE(SUM(failed), 0) AS failed,
                SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors
         FROM job_runs WHERE job = 'reminders' AND started_at >= ? AND started_at < ?`
      )
      .get(fromIso, toIso);
    const replies = this.db
      .prepare(
        `SELECT reply, COUNT(*) AS n FROM reminders WHERE replied_at >= ? AND replied_at < ? GROUP BY reply`
      )
      .all(fromIso, toIso);
    const inbound = this.db
      .prepare("SELECT COUNT(*) AS n FROM wa_messages WHERE direction = 'in' AND created_at >= ? AND created_at < ?")
      .get(fromIso, toIso).n;
    return { statuses, runs, replies, inbound };
  }
}

module.exports = { Store, STATUS_RANK };
