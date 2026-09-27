"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { runReminders, pickPhone } = require("../src/reminders");
const { WhatsAppError } = require("../src/whatsapp");
const { makeConfig, makeStore, fakeWa, fakeCliniko, appt, log } = require("./helpers");

const NOW = new Date("2026-09-29T10:00:00Z"); // 12:00 u Zagrebu
const START = "2026-09-30T08:00:00Z"; // sutra 10:00 u Zagrebu
const PHONE = "385981234567";

function setup({ appointments, patients, consent = true, failWith } = {}) {
  const store = makeStore();
  const config = makeConfig();
  const cliniko = fakeCliniko({
    appointments: appointments || [appt("a1", START)],
    patients: patients || {
      p1: { id: "p1", firstName: "Ana", lastName: "Horvat", phones: [{ type: "Mobile", number: "098 123 4567" }] },
    },
  });
  const wa = fakeWa({ failWith });
  if (consent) store.addConsent({ phone: PHONE, source: "test", givenAt: "2026-01-01T00:00:00Z" });
  const run = (now = NOW, extra = {}) => runReminders({ store, cliniko, wa, config, now, log, ...extra });
  return { store, config, cliniko, wa, run };
}

test("šalje predložak s imenom, datumom i satom u lokalnoj zoni", async () => {
  const { wa, store, run } = setup();
  const stats = await run();
  assert.equal(stats.sent, 1);
  assert.deepEqual(wa.sent[0].bodyParams, ["Ana Horvat", "30.9.2026.", "10:00"]);
  assert.equal(wa.sent[0].to, PHONE);
  const r = store.getReminder("a1", START);
  assert.equal(r.status, "sent");
  assert.equal(r.wamid, "wamid.T1");
  assert.equal(store.lastJobRun("reminders").sent, 1);
});

test("ponovno pokretanje ne šalje isti podsjetnik dvaput (G-82)", async () => {
  const { wa, run } = setup();
  await run();
  await run(new Date(NOW.getTime() + 15 * 60 * 1000));
  assert.equal(wa.sent.length, 1);
});

test("bez privole nema slanja (G-90)", async () => {
  const { wa, run } = setup({ consent: false });
  const stats = await run();
  assert.equal(wa.sent.length, 0);
  assert.equal(stats.noConsent, 1);
});

test("opozvana privola zaustavlja slanje", async () => {
  const { wa, store, run } = setup();
  store.revokeConsent(PHONE, "2026-09-01T00:00:00Z");
  await run();
  assert.equal(wa.sent.length, 0);
});

test("izvan vremena slanja čeka, a u 8 h pošalje", async () => {
  const early = "2026-10-01T05:00:00Z"; // termin 1.10. u 07:00 lokalno
  const { wa, run } = setup({ appointments: [appt("a1", early)] });
  const s1 = await run(new Date("2026-09-30T05:30:00Z")); // 07:30 dan prije – još rano
  assert.equal(s1.deferred, 1);
  assert.equal(wa.sent.length, 0);
  const s2 = await run(new Date("2026-09-30T06:00:00Z")); // 08:00
  assert.equal(s2.sent, 1);
  assert.equal(wa.sent[0].bodyParams[2], "07:00");
});

test("termin prekasno za podsjetnik (manje od 2 h) se preskače", async () => {
  const { wa, run } = setup({ appointments: [appt("a1", "2026-09-29T11:00:00Z")] }); // za 1 h
  const stats = await run();
  assert.equal(stats.planned, 0);
  assert.equal(wa.sent.length, 0);
});

test("otkazani termini i termini drugih poslovnica se preskaču", async () => {
  const { wa, config, run } = setup({
    appointments: [appt("a1", START, "p1", { cancelled: true }), appt("a2", START, "p1", { businessId: "b2" })],
  });
  config.cliniko.businessId = "b1";
  await run();
  assert.equal(wa.sent.length, 0);
});

test("termin otkazan neposredno prije slanja se ne šalje (G-81)", async () => {
  const { wa, store, cliniko, run } = setup();
  const original = cliniko.getAppointment.bind(cliniko);
  cliniko.getAppointment = async (id) => ({ ...(await original(id)), cancelled: true });
  await run();
  assert.equal(wa.sent.length, 0);
  assert.equal(store.getReminder("a1", START).status, "skipped");
});

test("pomaknut termin dobije novi podsjetnik za novo vrijeme", async () => {
  const { wa, cliniko, run } = setup();
  await run();
  cliniko.appointments[0].startsAt = "2026-09-30T09:00:00Z";
  await run(new Date(NOW.getTime() + 15 * 60 * 1000));
  assert.equal(wa.sent.length, 2);
  assert.equal(wa.sent[1].bodyParams[2], "11:00");
});

test("pacijent bez mobitela se preskače", async () => {
  const { wa, run } = setup({
    patients: { p1: { id: "p1", firstName: "Ana", lastName: "H", phones: [{ type: "Home", number: "023 123 456" }] } },
  });
  const stats = await run();
  assert.equal(stats.noPhone, 1);
  assert.equal(wa.sent.length, 0);
});

test("trajna greška primatelja: failed + zadatak recepciji, ostali idu dalje", async () => {
  const { wa, store, run } = setup({
    appointments: [appt("a1", START, "p1"), appt("a2", START, "p2")],
    patients: {
      p1: { id: "p1", firstName: "Ana", lastName: "H", phones: [{ type: "Mobile", number: "0981234567" }] },
      p2: { id: "p2", firstName: "Iva", lastName: "K", phones: [{ type: "Mobile", number: "0917654321" }] },
    },
    failWith: [new WhatsAppError({ message: "undeliverable", code: 131026, httpStatus: 400 })],
  });
  store.addConsent({ phone: "385917654321", source: "test", givenAt: "2026-01-01T00:00:00Z" });
  const stats = await run();
  assert.equal(stats.failed, 1);
  assert.equal(stats.sent, 1);
  assert.equal(store.getReminder("a1", START).status, "failed");
  const tasks = store.openTasks();
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].kind, "send_failed");
  assert.match(tasks[0].details, /G-41/);
});

test("globalna greška (istekao token) prekida posao i ostavlja termin na čekanju", async () => {
  const { wa, store, run } = setup({
    failWith: [new WhatsAppError({ message: "expired", code: 190, httpStatus: 401 })],
  });
  const stats = await run();
  assert.match(stats.error, /G-20/);
  const r = store.getReminder("a1", START);
  assert.equal(r.status, "pending");
  assert.equal(r.attempts, 0);
  assert.equal(store.openTasks().length, 0);
  assert.match(store.lastJobRun("reminders").error, /G-20/);
  // popravljen token -> sljedeći prolaz pošalje
  const again = await run(new Date(NOW.getTime() + 15 * 60 * 1000));
  assert.equal(again.sent, 1);
  assert.equal(wa.sent.length, 1);
});

test("privremena greška se ponavlja u sljedećim prolazima, pa odustaje", async () => {
  const tmp = () => new WhatsAppError({ message: "tmp", code: 131000, httpStatus: 500 });
  const { store, run } = setup({ failWith: [tmp(), tmp(), tmp()] });
  await run();
  assert.equal(store.getReminder("a1", START).status, "pending");
  await run(new Date(NOW.getTime() + 15 * 60 * 1000));
  assert.equal(store.getReminder("a1", START).status, "pending");
  await run(new Date(NOW.getTime() + 30 * 60 * 1000));
  const r = store.getReminder("a1", START);
  assert.equal(r.status, "failed");
  assert.equal(r.attempts, 3);
  assert.equal(store.openTasks()[0].kind, "send_failed");
});

test("slanje prekinuto usred poziva ide recepciji, ne šalje se ponovno", async () => {
  const { wa, store, run } = setup();
  store.claimReminder({
    appointmentId: "a1",
    startsAt: START,
    patientId: "p1",
    patientName: "Ana Horvat",
    phone: PHONE,
    now: "2026-09-29T09:00:00Z",
  });
  await run();
  assert.equal(wa.sent.length, 0);
  assert.equal(store.getReminder("a1", START).status, "unknown");
  assert.equal(store.openTasks()[0].kind, "send_unknown");
});

test("neisporučen podsjetnik nekoliko sati prije termina ide recepciji (G-51)", async () => {
  const { store, run } = setup();
  await run();
  // 3 h prije termina, i dalje samo 'accepted'
  await run(new Date("2026-09-30T05:00:00Z"));
  const tasks = store.openTasks();
  assert.equal(tasks.length, 1);
  assert.equal(tasks[0].kind, "undelivered");
  // ne ponavlja se
  await run(new Date("2026-09-30T05:15:00Z"));
  assert.equal(store.openTasks().length, 1);
});

test("probni način ništa ne šalje i ne piše u bazu", async () => {
  const { wa, store, run } = setup();
  const lines = [];
  const stats = await run(NOW, { dryRun: true, log: { info: (t) => lines.push(t), warn() {}, error() {} } });
  assert.equal(wa.sent.length, 0);
  assert.equal(stats.planned, 1);
  assert.equal(store.getReminder("a1", START), undefined);
  assert.equal(store.lastJobRun("reminders"), undefined);
  assert.ok(lines.some((l) => l.includes("[probno] termin #a1 30.9.2026. u 10:00")));
});

test("Cliniko nedostupan: posao bilježi grešku", async () => {
  const { cliniko, store, run } = setup();
  cliniko.listAppointments = async () => {
    throw new Error("Cliniko HTTP 503");
  };
  const stats = await run();
  assert.match(stats.error, /503/);
  assert.match(store.lastJobRun("reminders").error, /503/);
});

test("pickPhone preferira mobitel", () => {
  assert.equal(
    pickPhone([
      { type: "Home", number: "023 123 456" },
      { type: "Mobile", number: "091 765 4321" },
    ]),
    "385917654321"
  );
  assert.equal(pickPhone([{ type: "Other", number: "098 123 4567" }]), "385981234567");
  assert.equal(pickPhone([{ type: "Mobile", number: "nema" }]), null);
});
