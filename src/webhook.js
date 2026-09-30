import crypto from 'node:crypto';
import { log, maskPhone } from './log.js';

// Mala slova, bez kvačica ("Doći ću" i "doci cu" su isto; đ se ne rastavlja kroz NFD).
const norm = (s) =>
  String(s ?? '').trim().toLowerCase().replace(/đ/g, 'd').normalize('NFD').replace(/\p{M}/gu, '');

const CHANGE = /promjen|promijen|otkaz|pomak|pomakn|premjest|ne mogu|ne mozemo|necu|ne cu|ne dolaz|ne stig|ne stiz|sprijecen|bolest/;
const CONFIRM = /potvr|dolazim|dolazimo|doci cu/;
const NEGATION = /\b(ne|nisam|nismo|necu)\b/;

/**
 * Gumbi se prepoznaju po točnom tekstu. Slobodan tekst: najprije se traži
 * otkazivanje ili promjena, a potvrda samo ako u poruci nema nijekanja –
 * "Ne dolazim" nikad ne smije postati potvrda. Nejasno ostaje 'other' i
 * recepcija to pročita u aplikaciji.
 */
export function classifyReply(text, wa) {
  const t = norm(text);
  if (!t) return null;
  if (t === norm(wa.buttonConfirm)) return 'confirmed';
  if (t === norm(wa.buttonChange)) return 'change_requested';
  if (CHANGE.test(t)) return 'change_requested';
  if (CONFIRM.test(t) && !NEGATION.test(t)) return 'confirmed';
  return 'other';
}

/** Meta potpisuje svaki webhook App Secretom (X-Hub-Signature-256) – provjera nad sirovim tijelom. */
export function verifySignature(rawBody, header, appSecret) {
  if (!header || !appSecret) return false;
  const expected = 'sha256=' + crypto.createHmac('sha256', appSecret).update(rawBody).digest('hex');
  const a = Buffer.from(String(header));
  const b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

/** Obrada jednog webhook paketa (format WhatsApp Cloud API-ja). */
export async function handlePayload(payload, { cfg, db, wa, cliniko }) {
  for (const entry of payload?.entry || []) {
    for (const change of entry.changes || []) {
      const v = change.value || {};

      for (const st of v.statuses || []) {
        const err = st.errors?.[0];
        const msg = err ? `${err.title || ''} ${err.error_data?.details || ''}`.trim() : null;
        if (db.updateDelivery(st.id, st.status, err?.code ?? null, msg) && st.status === 'failed') {
          log.warn(`Isporuka nije uspjela (${maskPhone(st.recipient_id)}): ${err?.code} ${err?.title || ''}`);
        }
      }

      for (const m of v.messages || []) {
        if (!db.recordInbound(m.id, m.from)) continue; // već obrađeno

        const isButton = m.type === 'button' || m.type === 'interactive';
        const text =
          m.type === 'button' ? m.button?.text || m.button?.payload
          : m.type === 'interactive' ? m.interactive?.button_reply?.title
          : m.type === 'text' ? m.text?.body
          : '';

        const since = new Date(Date.now() - 3 * 86400_000).toISOString();
        const reminder = (m.context?.id && db.byWamid(m.context.id)) || db.latestForPhone(m.from, since);
        if (!reminder) continue;

        const kind = classifyReply(text, cfg.wa);
        // Slobodan tekst se ne sprema (GDPR) – recepcija ga vidi u aplikaciji na mobitelu.
        if (!kind || (kind === 'other' && !isButton)) continue;

        db.setReply(reminder.id, kind, isButton ? String(text).slice(0, 100) : null);
        log.info(`Odgovor pacijenta ${reminder.patient_id}: ${kind}`);

        const autoText = kind === 'confirmed' ? cfg.wa.replyConfirm : kind === 'change_requested' ? cfg.wa.replyChange : '';
        if (autoText && wa && !cfg.dryRun) {
          await wa.sendText(m.from, autoText).catch((e) => log.error('Automatski odgovor nije poslan:', e.message));
        }
        if (cfg.cliniko.writeNotes && cliniko && kind !== 'other') {
          await writeNote(cliniko, reminder, kind).catch((e) => log.error('Upis napomene u Cliniko nije uspio:', e.message));
        }
      }
    }
  }
}

async function writeNote(cliniko, reminder, kind) {
  const line = kind === 'confirmed' ? '[WhatsApp] Pacijent potvrdio dolazak.' : '[WhatsApp] Pacijent traži promjenu termina.';
  for (const a of JSON.parse(reminder.appointments)) {
    if (a.kind !== 'individual') continue;
    const appt = await cliniko.getIndividualAppointment(a.id);
    if (String(appt?.notes || '').includes(line)) continue;
    await cliniko.updateIndividualAppointment(a.id, { notes: appt?.notes ? `${appt.notes}\n${line}` : line });
  }
}

/**
 * HTTP obrada webhooka (bez Expressa).
 * GET  – Meta provjerava adresu (hub.challenge)
 * POST – događaji; bez ispravnog potpisa ništa se ne obrađuje
 */
export function handleWebhookRequest(req, res, rawBody, url, ctx) {
  const { cfg } = ctx;
  if (req.method === 'GET') {
    const p = url.searchParams;
    if (p.get('hub.mode') === 'subscribe' && cfg.wa.verifyToken && p.get('hub.verify_token') === cfg.wa.verifyToken) {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      return res.end(p.get('hub.challenge') ?? '');
    }
    res.writeHead(403);
    return res.end();
  }
  if (req.method !== 'POST') {
    res.writeHead(405);
    return res.end();
  }
  if (!verifySignature(rawBody, req.headers['x-hub-signature-256'], cfg.wa.appSecret)) {
    log.warn('Webhook s neispravnim potpisom odbijen.');
    res.writeHead(401);
    return res.end();
  }
  let payload;
  try {
    payload = JSON.parse(rawBody.toString('utf8'));
  } catch {
    res.writeHead(400);
    return res.end();
  }
  res.writeHead(200);
  res.end(); // odmah odgovori – obrada ide poslije, redom
  ctx.pending = (ctx.pending || Promise.resolve())
    .then(() => handlePayload(payload, ctx))
    .catch((e) => log.error('Obrada webhooka:', e.message));
}
