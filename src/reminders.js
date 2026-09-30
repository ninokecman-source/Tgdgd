import { idFromLink } from './cliniko.js';
import { pickMobile } from './phone.js';
import { hasConsent, loadAllowlist } from './consent.js';
import { dayRangeUtc, todayIn, addDays, formatForTemplate } from './time.js';
import { log, maskPhone } from './log.js';
import { isAccountError } from './whatsapp.js';

export const targetDate = (zone, daysAhead, now = new Date()) => addDays(todayIn(zone, now), daysAhead);

const inactive = (x) => Boolean(x.cancelled_at || x.archived_at || x.deleted_at || x.did_not_arrive === true);

/** Svi aktivni termini (individualni + grupni) za raspon, s poveznicom na pacijenta. */
export async function collectAppointments(cliniko, range, includeGroup) {
  const out = [];
  for await (const a of cliniko.individualAppointments(range.fromUtc, range.toUtc)) {
    if (inactive(a)) continue;
    const link = a.patient?.links?.self;
    if (link) out.push({ kind: 'individual', id: String(a.id), attendeeId: null, startsAt: a.starts_at, patientLink: link });
  }
  if (includeGroup) {
    for await (const g of cliniko.groupAppointments(range.fromUtc, range.toUtc)) {
      if (inactive(g)) continue;
      for await (const at of cliniko.attendees(g.id)) {
        if (inactive(at)) continue;
        const link = at.patient?.links?.self;
        if (link) out.push({ kind: 'group', id: String(g.id), attendeeId: String(at.id), startsAt: g.starts_at, patientLink: link });
      }
    }
  }
  return out;
}

/** Jedan podsjetnik po pacijentu po danu – za njegov najraniji termin. */
export function groupByPatient(appts) {
  const byPatient = new Map();
  for (const a of appts) {
    const pid = idFromLink(a.patientLink);
    if (!byPatient.has(pid)) byPatient.set(pid, []);
    byPatient.get(pid).push(a);
  }
  return [...byPatient.entries()].map(([patientId, list]) => {
    list.sort((x, y) => Date.parse(x.startsAt) - Date.parse(y.startsAt));
    return { patientId, patientLink: list[0].patientLink, startsAt: list[0].startsAt, appointments: list };
  });
}

/**
 * Glavni posao: pošalji podsjetnike za termine na dan `date` (zadano: sutra).
 * Sigurno za višestruko pokretanje – isti podsjetnik se nikad ne šalje dvaput.
 * Ako se termin premjesti na drugo vrijeme, pacijent dobiva novi podsjetnik.
 */
export async function runReminders({ cfg, cliniko, wa, db, date, dryRun = cfg.dryRun }) {
  const localDate = date || targetDate(cfg.timezone, cfg.daysAhead);
  const range = dayRangeUtc(localDate, cfg.timezone);
  const allowlist = cfg.consent.mode === 'allowlist' ? loadAllowlist(cfg.consent.file) : new Set();

  const appts = await collectAppointments(cliniko, range, cfg.cliniko.includeGroup);
  const groups = groupByPatient(appts);
  const summary = { date: localDate, appointments: appts.length, patients: groups.length, sent: 0, alreadySent: 0, failed: 0, deferred: 0, accountError: null, noPhone: 0, noConsent: 0, preview: [] };

  for (const g of groups) {
    const patient = await cliniko.patientByLink(g.patientLink);
    if (!patient || patient.archived_at || patient.deleted_at) continue;

    const name = (patient.preferred_first_name || patient.first_name || patient.last_name || '').trim();
    const phone = pickMobile(patient);
    const { datum, sat } = formatForTemplate(g.startsAt, cfg.timezone);
    const row = {
      reminder_key: `${g.patientId}|${g.startsAt}`,
      patient_id: g.patientId,
      patient_name: [patient.first_name, patient.last_name].filter(Boolean).join(' '),
      phone,
      starts_at: g.startsAt,
      local_date: localDate,
      appointments: JSON.stringify(g.appointments.map(({ kind, id, attendeeId }) => ({ kind, id, attendeeId }))),
    };

    if (!phone) {
      summary.noPhone++;
      if (!dryRun) db.markSkipped(row, 'skipped_no_phone');
      else summary.preview.push({ patient: row.patient_name, skip: 'nema mobitela' });
      continue;
    }
    if (!hasConsent(patient, phone, cfg.consent, allowlist)) {
      summary.noConsent++;
      if (!dryRun) db.markSkipped(row, 'skipped_no_consent');
      else summary.preview.push({ patient: row.patient_name, skip: 'nema privole' });
      continue;
    }

    const params = [name || 'pacijente', datum, sat];
    const to = cfg.testPhone || phone;

    if (dryRun) {
      const existing = db?.get(row.reminder_key);
      summary.preview.push({ patient: row.patient_name, to: maskPhone(to), params, alreadySent: existing?.status === 'sent' });
      continue;
    }

    if (!db.claim(row)) {
      summary.alreadySent++;
      continue;
    }
    try {
      const wamid = await wa.sendTemplate(to, params);
      db.markSent(row.reminder_key, wamid);
      summary.sent++;
      log.info(`Poslan podsjetnik: pacijent ${g.patientId}, ${datum} ${sat}, ${maskPhone(to)}`);
    } catch (err) {
      if (isAccountError(err)) {
        // Nije do pacijenta: ponovit će se u sljedećem krugu, čim se uzrok ukloni.
        db.markDeferred(row.reminder_key, err.code ?? 'ERR', err.message);
        summary.deferred++;
        summary.accountError = err.message;
        log.error(`Podsjetnik NIJE poslan (greška računa/postavki, ponovit će se): pacijent ${g.patientId}: ${err.message}`);
      } else {
        db.markFailed(row.reminder_key, err.code ?? 'ERR', err.message);
        summary.failed++;
        log.error(`Podsjetnik NIJE poslan: pacijent ${g.patientId} (${maskPhone(to)}): ${err.message}`);
      }
    }
  }
  return summary;
}
