"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const { verifySignature, handlePayload, classifyButton } = require("../src/webhook");
const { makeConfig, makeStore, fakeWa, log } = require("./helpers");

const PHONE = "385981234567";
const START = "2026-09-30T08:00:00Z";
const NOW = new Date("2026-09-29T12:00:00Z");

function ctx() {
  const store = makeStore();
  const config = makeConfig();
  const wa = fakeWa();
  return { store, config, wa, log, now: () => NOW };
}

function sentReminder(c, wamid = "wamid.R1") {
  c.store.claimReminder({ appointmentId: "a1", startsAt: START, patientId: "p1", patientName: "Ana Horvat", phone: PHONE, now: "2026-09-29T10:00:00Z" });
  c.store.markReminderSent({ appointmentId: "a1", startsAt: START, wamid, phone: PHONE, now: "2026-09-29T10:00:00Z" });
}

const envelope = (value, field = "messages") => ({
  object: "whatsapp_business_account",
  entry: [{ id: "WABA", changes: [{ field, value: { messaging_product: "whatsapp", metadata: { phone_number_id: "PNID" }, ...value } }] }],
});

const button = (id, text, contextId = "wamid.R1") => ({
  from: PHONE,
  id,
  timestamp: "1790690000",
  type: "button",
  context: contextId ? { from: "38523000000", id: contextId } : undefined,
  button: { text, payload: text },
});

const textMsg = (id, body) => ({ from: PHONE, id, timestamp: "1790690000", type: "text", text: { body } });
const status = (id, s, extra = {}) => ({ id, status: s, timestamp: "1790690000", recipient_id: PHONE, ...extra });

test("potpis: ispravan prolazi, izmijenjeno tijelo i krivi secret ne (G-32)", () => {
  const body = Buffer.from('{"a":1}');
  const sig = "sha256=" + crypto.createHmac("sha256", "app-secret").update(body).digest("hex");
  assert.equal(verifySignature(body, sig, "app-secret"), true);
  assert.equal(verifySignature(Buffer.from('{"a":2}'), sig, "app-secret"), false);
  assert.equal(verifySignature(body, sig, "verify-token"), false);
  assert.equal(verifySignature(body, "", "app-secret"), false);
  assert.equal(verifySignature(body, "sha256=abc", "app-secret"), false);
});

test("gumb 'Potvrđujem' potvrđuje termin preko context.id i zahvaljuje", async () => {
  const c = ctx();
  sentReminder(c);
  await handlePayload(envelope({ messages: [button("wamid.IN1", "Potvrđujem")] }), c);
  const r = c.store.getReminder("a1", START);
  assert.equal(r.reply, "confirmed");
  assert.equal(c.store.openTasks().length, 0);
  assert.deepEqual(c.wa.sent.map((s) => s.body), ["Hvala, potvrđeno."]);
});

test("gumb 'Trebam promjenu' otvara zadatak recepciji", async () => {
  const c = ctx();
  sentReminder(c);
  await handlePayload(envelope({ messages: [button("wamid.IN1", "Trebam promjenu")] }), c);
  assert.equal(c.store.getReminder("a1", START).reply, "change_requested");
  const [task] = c.store.openTasks();
  assert.equal(task.kind, "change_requested");
  assert.match(task.details, /Ana Horvat traži promjenu termina 30\.9\.2026\. u 10:00 h/);
});

test("isti događaj dvaput se obradi samo jednom (G-33)", async () => {
  const c = ctx();
  sentReminder(c);
  const payload = envelope({ messages: [button("wamid.IN1", "Trebam promjenu")] });
  await handlePayload(payload, c);
  await handlePayload(payload, c);
  assert.equal(c.store.openTasks().length, 1);
  assert.equal(c.wa.sent.length, 1);
});

test("gumb bez veze s terminom ne mijenja ništa, ide recepciji (G-83)", async () => {
  const c = ctx();
  sentReminder(c);
  await handlePayload(envelope({ messages: [button("wamid.IN1", "Potvrđujem", "wamid.NEPOZNAT")] }), c);
  assert.equal(c.store.getReminder("a1", START).reply, null);
  assert.equal(c.store.openTasks()[0].kind, "patient_message");
});

test("slobodna poruka ide u inbox recepcije s tekstom", async () => {
  const c = ctx();
  await handlePayload(envelope({ messages: [textMsg("wamid.IN2", "Kasnim 10 minuta")] }), c);
  const [task] = c.store.openTasks();
  assert.equal(task.kind, "patient_message");
  assert.equal(task.message_body, "Kasnim 10 minuta");
  assert.equal(c.wa.sent.length, 0);
});

test("STOP opoziva privolu i potvrđuje odjavu", async () => {
  const c = ctx();
  c.store.addConsent({ phone: PHONE, source: "test", givenAt: "2026-01-01T00:00:00Z" });
  await handlePayload(envelope({ messages: [textMsg("wamid.IN3", " stop ")] }), c);
  assert.equal(c.store.hasConsent(PHONE), false);
  assert.equal(c.store.openTasks()[0].kind, "opt_out");
  assert.deepEqual(c.wa.sent.map((s) => s.body), ["Odjavljeni ste."]);
});

test("slika se ne preuzima, recepcija dobije napomenu", async () => {
  const c = ctx();
  await handlePayload(envelope({ messages: [{ from: PHONE, id: "wamid.IN4", timestamp: "1790690000", type: "image", image: { id: "m1" } }] }), c);
  assert.match(c.store.openTasks()[0].details, /sliku/);
});

test("statusi obrnutim redom ne vraćaju 'read' na 'delivered' (G-34)", async () => {
  const c = ctx();
  sentReminder(c);
  await handlePayload(envelope({ statuses: [status("wamid.R1", "read"), status("wamid.R1", "delivered"), status("wamid.R1", "sent")] }), c);
  const row = c.store.db.prepare("SELECT status FROM wa_messages WHERE wamid = 'wamid.R1'").get();
  assert.equal(row.status, "read");
});

test("failed je konačan i otvara zadatak s rezervnim kanalom (tok 4)", async () => {
  const c = ctx();
  sentReminder(c);
  await handlePayload(
    envelope({ statuses: [status("wamid.R1", "failed", { errors: [{ code: 131026, title: "Message undeliverable" }] })] }),
    c
  );
  await handlePayload(envelope({ statuses: [status("wamid.R1", "delivered")] }), c);
  const row = c.store.db.prepare("SELECT status, error_code FROM wa_messages WHERE wamid = 'wamid.R1'").get();
  assert.deepEqual({ ...row }, { status: "failed", error_code: 131026 });
  assert.equal(c.store.getReminder("a1", START).status, "failed");
  const [task] = c.store.openTasks();
  assert.equal(task.kind, "delivery_failed");
  assert.match(task.details, /G-41/);
});

test("događaji za drugi broj istog WABA-a se ignoriraju", async () => {
  const c = ctx();
  const p = envelope({ messages: [textMsg("wamid.IN5", "bok")] });
  p.entry[0].changes[0].value.metadata.phone_number_id = "DRUGI";
  await handlePayload(p, c);
  assert.equal(c.store.openTasks().length, 0);
});

test("odbijen predložak otvara zadatak (G-60/G-67)", async () => {
  const c = ctx();
  await handlePayload(
    envelope({ event: "PAUSED", message_template_name: "podsjetnik_termin", message_template_language: "hr", reason: "LOW_QUALITY" }, "message_template_status_update"),
    c
  );
  const [task] = c.store.openTasks();
  assert.equal(task.kind, "template");
  assert.match(task.details, /PAUSED – LOW_QUALITY/);
});

test("prepoznavanje gumba ne ovisi o kvačicama i velikim slovima", () => {
  const t = makeConfig().template;
  assert.equal(classifyButton("POTVRĐUJEM", null, t), "confirmed");
  assert.equal(classifyButton("potvrdujem", null, t), "confirmed");
  assert.equal(classifyButton("x", "Trebam promjenu", t), "change_requested");
  assert.equal(classifyButton("Nešto treće", null, t), null);
});
