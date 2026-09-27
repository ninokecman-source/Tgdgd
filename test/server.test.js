"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const { createApp } = require("../src/server");
const { makeConfig, makeStore, fakeWa, log } = require("./helpers");

const PHONE = "385981234567";

async function start(overrides = {}) {
  const ctx = { config: makeConfig(overrides), store: makeStore(), wa: fakeWa(), log, now: () => new Date() };
  const server = createApp(ctx).listen(0, "127.0.0.1");
  await new Promise((r) => server.once("listening", r));
  const base = `http://127.0.0.1:${server.address().port}`;
  return { ctx, base, close: () => new Promise((r) => server.close(r)) };
}

const auth = "Basic " + Buffer.from("recepcija:tajna").toString("base64");
const sign = (body) => "sha256=" + crypto.createHmac("sha256", "app-secret").update(body).digest("hex");
const waitFor = async (fn) => {
  for (let i = 0; i < 50 && !fn(); i++) await new Promise((r) => setTimeout(r, 10));
};

test("verifikacija webhooka vraća čisti challenge (G-30)", async () => {
  const s = await start();
  try {
    const q = new URLSearchParams({ "hub.mode": "subscribe", "hub.verify_token": "verify-token-dugi-nasumicni-niz", "hub.challenge": "123" });
    const ok = await fetch(`${s.base}/whatsapp/webhook?${q}`);
    assert.equal(ok.status, 200);
    assert.equal(await ok.text(), "123");
    q.set("hub.verify_token", "krivo");
    assert.equal((await fetch(`${s.base}/whatsapp/webhook?${q}`)).status, 403);
  } finally {
    await s.close();
  }
});

test("POST s krivim potpisom se odbija, s ispravnim sprema i obrađuje", async () => {
  const s = await start();
  try {
    const body = JSON.stringify({
      entry: [{ changes: [{ field: "messages", value: { metadata: { phone_number_id: "PNID" }, messages: [{ from: PHONE, id: "wamid.A", timestamp: "1790690000", type: "text", text: { body: "Pozdrav" } }] } }] }],
    });
    const bad = await fetch(`${s.base}/whatsapp/webhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Hub-Signature-256": sign(body + " ") },
      body,
    });
    assert.equal(bad.status, 401);
    const good = await fetch(`${s.base}/whatsapp/webhook`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Hub-Signature-256": sign(body) },
      body,
    });
    assert.equal(good.status, 200);
    await waitFor(() => s.ctx.store.openTasks().length === 1);
    assert.equal(s.ctx.store.openTasks()[0].message_body, "Pozdrav");
    assert.equal(s.ctx.store.pendingEvents().length, 0);
  } finally {
    await s.close();
  }
});

test("/zdravlje javlja 503 dok se posao podsjetnika ne pokrene, pa 200", async () => {
  const s = await start();
  try {
    const r1 = await fetch(`${s.base}/zdravlje`);
    assert.equal(r1.status, 503);
    const id = s.ctx.store.startJob("reminders", new Date().toISOString());
    s.ctx.store.finishJob(id, { at: new Date().toISOString(), planned: 0, sent: 0, failed: 0 });
    const r2 = await fetch(`${s.base}/zdravlje`);
    assert.equal(r2.status, 200);
    assert.equal((await r2.json()).ok, true);
  } finally {
    await s.close();
  }
});

test("/zdravlje javlja poruke bez statusa s webhooka (G-31)", async () => {
  const s = await start();
  try {
    const id = s.ctx.store.startJob("reminders", new Date().toISOString());
    s.ctx.store.finishJob(id, { at: new Date().toISOString(), planned: 1, sent: 1, failed: 0 });
    s.ctx.store.insertOutbound({ wamid: "wamid.old", phone: PHONE, type: "template", createdAt: new Date(Date.now() - 3600e3).toISOString() });
    const r = await fetch(`${s.base}/zdravlje`);
    assert.equal(r.status, 503);
    assert.match((await r.json()).problems[0], /G-31/);
  } finally {
    await s.close();
  }
});

test("recepcija traži lozinku, a obrasci CSRF token", async () => {
  const s = await start();
  try {
    assert.equal((await fetch(`${s.base}/recepcija`)).status, 401);
    const wrong = "Basic " + Buffer.from("recepcija:krivo").toString("base64");
    assert.equal((await fetch(`${s.base}/recepcija`, { headers: { Authorization: wrong } })).status, 401);

    const page = await fetch(`${s.base}/recepcija`, { headers: { Authorization: auth } });
    assert.equal(page.status, 200);
    const html = await page.text();
    const csrf = /name="_csrf" value="([0-9a-f]+)"/.exec(html)[1];

    const noToken = await fetch(`${s.base}/recepcija/privola`, {
      method: "POST",
      headers: { Authorization: auth, "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ phone: "0981234567", source: "obrazac" }),
      redirect: "manual",
    });
    assert.equal(noToken.status, 403);
    assert.equal(s.ctx.store.hasConsent(PHONE), false);

    const withToken = await fetch(`${s.base}/recepcija/privola`, {
      method: "POST",
      headers: { Authorization: auth, "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ _csrf: csrf, phone: "098 123 4567", source: "obrazac" }),
      redirect: "manual",
    });
    assert.equal(withToken.status, 303);
    assert.equal(s.ctx.store.hasConsent(PHONE), true);
  } finally {
    await s.close();
  }
});

test("odgovor recepcije: unutar 24 h šalje, izvan prozora odbija (G-40)", async () => {
  const s = await start();
  try {
    const html = await (await fetch(`${s.base}/recepcija`, { headers: { Authorization: auth } })).text();
    const csrf = /name="_csrf" value="([0-9a-f]+)"/.exec(html)[1];
    const post = (phone) =>
      fetch(`${s.base}/recepcija/odgovor`, {
        method: "POST",
        headers: { Authorization: auth, "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ _csrf: csrf, phone, text: "Vidimo se u 10." }),
        redirect: "manual",
      });

    const r1 = await post(PHONE);
    assert.match(decodeURIComponent(r1.headers.get("location")), /više od 24 h/);
    assert.equal(s.ctx.wa.sent.length, 0);

    s.ctx.store.insertInbound({ wamid: "wamid.in", phone: PHONE, type: "text", body: "?", createdAt: new Date().toISOString() });
    const r2 = await post(PHONE);
    assert.match(decodeURIComponent(r2.headers.get("location")), /Odgovor poslan/);
    assert.equal(s.ctx.wa.sent[0].body, "Vidimo se u 10.");
  } finally {
    await s.close();
  }
});

test("poruka pacijenta se na stranici prikazuje escapirano", async () => {
  const s = await start();
  try {
    const id = s.ctx.store.insertInbound({ wamid: "wamid.x", phone: PHONE, type: "text", body: "<script>alert(1)</script>", createdAt: new Date().toISOString() });
    s.ctx.store.addTask({ kind: "patient_message", phone: PHONE, messageId: id, details: "Poruka pacijenta", createdAt: new Date().toISOString() });
    const html = await (await fetch(`${s.base}/recepcija`, { headers: { Authorization: auth } })).text();
    assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
    assert.ok(!html.includes("<script>alert(1)"));
  } finally {
    await s.close();
  }
});

test("bez korisnika i lozinke recepcija ne postoji", async () => {
  const s = await start({ reception: { user: "", password: "" } });
  try {
    assert.equal((await fetch(`${s.base}/recepcija`)).status, 404);
  } finally {
    await s.close();
  }
});
