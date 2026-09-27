"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { WhatsAppClient, WhatsAppError, cleanParam } = require("../src/whatsapp");

function fakeFetch(responses) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init, body: init.body ? JSON.parse(init.body) : null });
    const r = responses.shift();
    if (r instanceof Error) throw r;
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  };
  fn.calls = calls;
  return fn;
}

function client(fetchImpl) {
  return new WhatsAppClient({
    token: "tok",
    phoneNumberId: "PNID",
    wabaId: "WABA",
    graphVersion: "v23.0",
    fetchImpl,
    sleepImpl: async () => {},
  });
}

test("predložak ide na PHONE_NUMBER_ID s tri očišćena parametra", async () => {
  const f = fakeFetch([{ status: 200, body: { messages: [{ id: "wamid.1" }] } }]);
  const wamid = await client(f).sendTemplate({
    to: "385981234567",
    name: "podsjetnik_termin",
    language: "hr",
    bodyParams: ["Ana\n  Horvat", "30.9.2026.", "14:30"],
  });
  assert.equal(wamid, "wamid.1");
  const { url, init, body } = f.calls[0];
  assert.equal(url, "https://graph.facebook.com/v23.0/PNID/messages");
  assert.equal(init.headers.Authorization, "Bearer tok");
  assert.equal(body.messaging_product, "whatsapp");
  assert.equal(body.to, "385981234567");
  assert.deepEqual(body.template.language, { code: "hr" });
  assert.deepEqual(
    body.template.components[0].parameters.map((p) => p.text),
    ["Ana Horvat", "30.9.2026.", "14:30"]
  );
});

test("privremena greška se ponavlja, pa uspije", async () => {
  const f = fakeFetch([
    { status: 500, body: { error: { code: 131000, message: "Something went wrong" } } },
    new Error("socket hang up"),
    { status: 200, body: { messages: [{ id: "wamid.2" }] } },
  ]);
  assert.equal(await client(f).sendText({ to: "385981234567", body: "hi" }), "wamid.2");
  assert.equal(f.calls.length, 3);
});

test("trajna greška se ne ponavlja i nosi opis iz kataloga", async () => {
  const f = fakeFetch([{ status: 400, body: { error: { code: 131026, message: "Message undeliverable" } } }]);
  await assert.rejects(
    client(f).sendText({ to: "385981234567", body: "hi" }),
    (err) => err instanceof WhatsAppError && err.code === 131026 && err.info.ref === "G-41"
  );
  assert.equal(f.calls.length, 1);
});

test("privremene greške nakon 1+4 pokušaja odustaju", async () => {
  const errs = Array.from({ length: 5 }, () => ({ status: 503, body: { error: { code: 131000, message: "x" } } }));
  const f = fakeFetch(errs);
  await assert.rejects(client(f).sendText({ to: "1", body: "x" }), WhatsAppError);
  assert.equal(f.calls.length, 5);
});

test("cleanParam uklanja nove redove, tabove i višestruke razmake (G-66)", () => {
  assert.equal(cleanParam("  a\t\tb \n\n c     d "), "a b c d");
  assert.equal(cleanParam("x".repeat(300)).length, 200);
});
