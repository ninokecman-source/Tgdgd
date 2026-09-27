"use strict";
// Tok 1: podsjetnik 24 h prije termina. Pokreće se iz crona svakih 15 min:
//   npm run podsjetnici             – stvarno slanje
//   npm run podsjetnici -- --probno – samo ispiše što bi poslao

const { WhatsAppError } = require("./whatsapp");
const { describe, formatError } = require("./errors");
const { normalizePhone, isMobile, maskPhone } = require("./phone");
const { formatDate, formatTime, inSendingWindow, iso, addHours, addMinutes } = require("./timeutil");

const STALE_SENDING_MINUTES = 30;

// Mobitel iz Clinika ima prednost; inače bilo koji broj koji je mobilni.
function pickPhone(phones) {
  const normalized = phones
    .map((p) => ({ type: (p.type || "").toLowerCase(), phone: normalizePhone(p.number) }))
    .filter((p) => p.phone);
  const mobile = normalized.find((p) => p.type === "mobile" && isMobile(p.phone));
  if (mobile) return mobile.phone;
  const any = normalized.find((p) => isMobile(p.phone));
  return any ? any.phone : null;
}

async function runReminders({ store, cliniko, wa, config, now = new Date(), log, dryRun = false }) {
  const nowIso = iso(now);
  const tz = config.timezone;
  const stats = { planned: 0, sent: 0, failed: 0, retryLater: 0, noConsent: 0, noPhone: 0, deferred: 0, error: null };
  const jobId = dryRun ? null : store.startJob("reminders", nowIso);

  try {
    if (!dryRun) recoverStaleSending({ store, now, log });

    const from = addHours(now, config.reminderMinHoursBefore);
    const to = addHours(now, config.reminderHoursBefore);
    const sendingAllowed = inSendingWindow(now, tz, config.sendHours);

    const appointments = (await cliniko.listAppointments(from, to)).filter(
      (a) =>
        !a.cancelled &&
        !a.archived &&
        !a.didNotArrive &&
        (!config.cliniko.businessId || a.businessId === config.cliniko.businessId)
    );

    const patients = new Map();
    for (const appt of appointments) {
      const existing = store.getReminder(appt.id, appt.startsAt);
      if (existing && existing.status !== "pending") continue;

      if (!patients.has(appt.patientId)) {
        patients.set(appt.patientId, appt.patientId ? await cliniko.getPatient(appt.patientId) : null);
      }
      const patient = patients.get(appt.patientId);
      const phone = patient ? pickPhone(patient.phones) : null;
      if (!phone) {
        stats.noPhone++;
        continue;
      }
      if (!store.hasConsent(phone)) {
        stats.noConsent++;
        continue;
      }
      stats.planned++;

      const start = new Date(appt.startsAt);
      const name = `${patient.firstName} ${patient.lastName}`.trim() || config.template.nameFallback;
      const date = formatDate(start, tz);
      const time = formatTime(start, tz);

      if (dryRun) {
        const note = sendingAllowed ? "" : " (sada je izvan vremena slanja – čekao bi)";
        log.info(`[probno] termin #${appt.id} ${date} u ${time} -> ${maskPhone(phone)}${note}`);
        continue;
      }
      if (!sendingAllowed) {
        stats.deferred++;
        continue;
      }

      const key = { appointmentId: appt.id, startsAt: appt.startsAt };
      const claimed = store.claimReminder({
        ...key,
        patientId: patient.id,
        patientName: name === config.template.nameFallback ? null : name,
        phone,
        now: nowIso,
      });
      if (!claimed) continue;

      // G-81: neposredno prije slanja ponovno provjeri termin.
      let fresh;
      try {
        fresh = await cliniko.getAppointment(appt.id);
      } catch (err) {
        store.setReminderStatus({ ...key, status: "pending", now: nowIso });
        log.warn(`Termin #${appt.id}: Cliniko provjera nije uspjela (${err.message}), pokušat ću ponovno`);
        continue;
      }
      if (!fresh || fresh.cancelled || fresh.archived || fresh.startsAt !== appt.startsAt) {
        store.setReminderStatus({ ...key, status: "skipped", note: "otkazan ili pomaknut prije slanja", now: nowIso });
        log.info(`Termin #${appt.id} otkazan ili pomaknut u međuvremenu – ne šaljem`);
        continue;
      }

      try {
        const wamid = await wa.sendTemplate({
          to: phone,
          name: config.template.name,
          language: config.template.language,
          bodyParams: [name, date, time],
        });
        store.markReminderSent({ ...key, wamid, phone, now: nowIso });
        stats.sent++;
        log.info(`Podsjetnik poslan: termin #${appt.id} ${date} u ${time} -> ${maskPhone(phone)}`);
      } catch (err) {
        const outcome = handleSendError({ err, key, existing, store, config, phone, name, date, time, now: nowIso, log });
        if (outcome === "abort") {
          stats.error = formatError(err.code, err.httpStatus);
          break;
        }
        if (outcome === "failed") stats.failed++;
        else stats.retryLater++;
      }
    }

    if (!dryRun) {
      alertUndelivered({ store, config, now, log });
      warnUnconfirmed({ store, config, now, log });
      store.purge({
        beforeIso: iso(addHours(now, -24 * config.retentionDays)),
        eventsBeforeIso: iso(addHours(now, -24 * 7)),
      });
    }
  } catch (err) {
    stats.error = err.message;
    log.error(`Podsjetnici prekinuti: ${err.message}`);
  }

  if (!dryRun) {
    store.finishJob(jobId, {
      at: iso(new Date()),
      planned: stats.planned,
      sent: stats.sent,
      failed: stats.failed,
      error: stats.error,
    });
  }
  log.info(
    `Poslano ${stats.sent} / planirano ${stats.planned}` +
      ` (neuspjelo ${stats.failed}, ponovit će se ${stats.retryLater}, čeka vrijeme slanja ${stats.deferred},` +
      ` bez privole ${stats.noConsent}, bez mobitela ${stats.noPhone})`
  );
  return stats;
}

function handleSendError({ err, key, existing, store, config, phone, name, date, time, now, log }) {
  if (!(err instanceof WhatsAppError)) {
    store.setReminderStatus({ ...key, status: "pending", countAttempt: true, now });
    log.error(`Termin #${key.appointmentId}: neočekivana greška pri slanju: ${err.message}`);
    return "retry";
  }
  const info = describe(err.code, err.httpStatus);
  const reason = formatError(err.code, err.httpStatus);

  // Kvar postavki ili limit računa pogodio bi sve pacijente: stani, ostavi
  // termin na čekanju i ne troši mu pokušaje.
  if (info.scope === "global") {
    store.setReminderStatus({ ...key, status: "pending", errorCode: err.code, now });
    log.error(`Slanje prekinuto: ${reason}`);
    return "abort";
  }

  const attempts = (existing ? existing.attempts : 0) + 1;
  if (info.temporary && attempts < config.maxSendAttempts) {
    store.setReminderStatus({ ...key, status: "pending", errorCode: err.code, countAttempt: true, now });
    log.warn(`Termin #${key.appointmentId} (${maskPhone(phone)}): ${reason} – pokušaj ${attempts}/${config.maxSendAttempts}`);
    return "retry";
  }

  store.setReminderStatus({ ...key, status: "failed", errorCode: err.code, countAttempt: true, now });
  store.addTask({
    kind: "send_failed",
    appointmentId: key.appointmentId,
    phone,
    details: `Podsjetnik za ${name}, termin ${date} u ${time} h, nije poslan – javite se telefonom ili SMS-om. ${reason}`,
    createdAt: now,
  });
  log.warn(`Termin #${key.appointmentId} (${maskPhone(phone)}): ${reason}`);
  return "failed";
}

// G-82: proces je pao usred slanja – ne znamo je li poruka otišla. Ne šalje
// se ponovno (dupli podsjetnik je gori od nijednog); recepcija provjerava.
function recoverStaleSending({ store, now, log }) {
  for (const r of store.staleSending(iso(addMinutes(now, -STALE_SENDING_MINUTES)))) {
    store.setReminderStatus({
      appointmentId: r.appointment_id,
      startsAt: r.starts_at,
      status: "unknown",
      note: "slanje prekinuto",
      now: iso(now),
    });
    store.addTask({
      kind: "send_unknown",
      appointmentId: r.appointment_id,
      phone: r.patient_phone,
      details: `${r.patient_name || "Pacijent"}: slanje podsjetnika je prekinuto i ne zna se je li stigao – po potrebi nazovite`,
      createdAt: iso(now),
    });
    log.warn(`Termin #${r.appointment_id}: slanje prekinuto usred poziva, predano recepciji`);
  }
}

// G-51: nema "delivered" do X sati prije termina -> rezervni kanal.
function alertUndelivered({ store, config, now, log }) {
  const until = addHours(now, config.undeliveredAlertHours);
  for (const r of store.undeliveredBefore(iso(now), iso(until))) {
    const start = new Date(r.starts_at);
    store.addTask({
      kind: "undelivered",
      appointmentId: r.appointment_id,
      phone: r.patient_phone,
      details: `${r.patient_name || "Pacijent"} još nije primio/la podsjetnik, a termin je ${formatDate(start, config.timezone)} u ${formatTime(start, config.timezone)} h – nazovite ili pošaljite SMS`,
      createdAt: iso(now),
    });
    store.markUndeliveredAlerted(r.appointment_id, r.starts_at);
    log.warn(`Termin #${r.appointment_id}: podsjetnik nije isporučen, predano recepciji`);
  }
}

// G-31/G-35: API je prihvatio poruke, ali webhook nije javio ni "sent".
function warnUnconfirmed({ store, config, now, log }) {
  const n = store.countUnconfirmedBefore(iso(addMinutes(now, -config.health.maxUnconfirmedMinutes)));
  if (n) log.warn(`${n} poslanih poruka bez ijednog statusa s webhooka – provjeri webhook (G-31, G-35)`);
}

async function main() {
  const { loadConfig, requireKeys } = require("./config");
  const { Store } = require("./db");
  const { ClinikoClient } = require("./cliniko");
  const { WhatsAppClient } = require("./whatsapp");
  const { createLogger } = require("./log");

  const dryRun = process.argv.includes("--probno");
  const log = createLogger();
  const config = loadConfig();
  requireKeys(
    config,
    dryRun
      ? ["cliniko.apiKey", "cliniko.userAgent"]
      : ["cliniko.apiKey", "cliniko.userAgent", "wa.token", "wa.phoneNumberId", "wa.graphVersion"]
  );
  const store = new Store(config.dbPath);
  try {
    const stats = await runReminders({
      store,
      cliniko: new ClinikoClient(config.cliniko),
      wa: new WhatsAppClient(config.wa),
      config,
      log,
      dryRun,
    });
    process.exitCode = stats.error ? 1 : 0;
  } finally {
    store.close();
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`[GREŠKA] ${err.message}`);
    process.exitCode = 1;
  });
}

module.exports = { runReminders, pickPhone };
