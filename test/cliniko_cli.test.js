"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { ClinikoClient } = require("../src/cliniko");
const { parseCsv, main } = require("../src/cli");

function res(status, body, headers = {}) {
  return { ok: status < 400, status, json: async () => body, headers: { get: (h) => headers[h.toLowerCase()] ?? null } };
}

test("Cliniko: filter po vremenu, straničenje i autentikacija", async () => {
  const calls = [];
  const pages = [
    res(200, {
      individual_appointments: [
        { id: 11, starts_at: "2026-09-30T08:00:00Z", cancelled_at: null, patient: { links: { self: "https://api.eu1.cliniko.com/v1/patients/501" } }, business: { links: { self: "https://api.eu1.cliniko.com/v1/businesses/7" } } },
      ],
      links: { next: "https://api.eu1.cliniko.com/v1/individual_appointments?page=2" },
    }),
    res(429, {}, { "retry-after": "0" }),
    res(200, {
      individual_appointments: [{ id: 12, starts_at: "2026-09-30T09:00:00Z", cancelled_at: "2026-09-29T08:00:00Z", patient: { links: { self: "/v1/patients/502" } } }],
      links: {},
    }),
  ];
  const c = new ClinikoClient({
    apiKey: "KEY-eu1",
    userAgent: "Proprio test (a@b.hr)",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return pages.shift();
    },
    sleepImpl: async () => {},
  });
  const list = await c.listAppointments(new Date("2026-09-29T12:00:00Z"), new Date("2026-09-30T10:00:00Z"));
  assert.deepEqual(
    list.map((a) => [a.id, a.patientId, a.businessId, a.cancelled]),
    [["11", "501", "7", false], ["12", "502", null, true]]
  );
  const first = new URL(calls[0].url);
  assert.equal(first.origin + first.pathname, "https://api.eu1.cliniko.com/v1/individual_appointments");
  assert.deepEqual(first.searchParams.getAll("q[]"), ["starts_at:>=2026-09-29T12:00:00.000Z", "starts_at:<2026-09-30T10:00:00.000Z"]);
  assert.equal(calls[0].init.headers.Authorization, "Basic " + Buffer.from("KEY-eu1:").toString("base64"));
  assert.equal(calls[0].init.headers["User-Agent"], "Proprio test (a@b.hr)");
  assert.equal(calls.length, 3); // druga stranica je ponovljena nakon 429
});

test("Cliniko: obrisan termin je null, pacijent daje ime i brojeve", async () => {
  const replies = [
    res(404, {}),
    res(200, { id: 501, first_name: "Ana", preferred_first_name: "", last_name: "Horvat", patient_phone_numbers: [{ phone_type: "Mobile", number: "098 123 4567" }] }),
  ];
  const c = new ClinikoClient({ apiKey: "KEY-eu1", userAgent: "t", fetchImpl: async () => replies.shift(), sleepImpl: async () => {} });
  assert.equal(await c.getAppointment("11"), null);
  assert.deepEqual(await c.getPatient("501"), {
    id: "501",
    firstName: "Ana",
    lastName: "Horvat",
    phones: [{ type: "Mobile", number: "098 123 4567" }],
  });
});

test("Cliniko: 401 daje jasnu poruku", async () => {
  const c = new ClinikoClient({ apiKey: "KEY-eu1", userAgent: "t", fetchImpl: async () => res(401, {}), sleepImpl: async () => {} });
  await assert.rejects(c.getUser(), /CLINIKO_API_KEY/);
});

test("CSV privola: točka-zarez iz Excela, navodnici i BOM", () => {
  assert.deepEqual(parseCsv('﻿telefon;izvor\n"098 123 4567";obrazac\n'), [
    ["telefon", "izvor"],
    ["098 123 4567", "obrazac"],
  ]);
  assert.deepEqual(parseCsv("0981234567,web,2026-05-01,501"), [["0981234567", "web", "2026-05-01", "501"]]);
});

test("alat: uvoz privola, opoziv i izvještaj", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "wa-"));
  const envFile = path.join(dir, ".env");
  fs.writeFileSync(envFile, `DB_PATH=${path.join(dir, "db.sqlite3")}\n`);
  const csv = path.join(dir, "privole.csv");
  fs.writeFileSync(csv, "telefon;izvor;datum\n098 123 4567;obrazac;2026-05-01\nkrivo;obrazac\n091 765 4321;web\n");
  const saved = { ENV_FILE: process.env.ENV_FILE, DB_PATH: process.env.DB_PATH };
  process.env.ENV_FILE = envFile;
  delete process.env.DB_PATH;
  const out = [];
  t.mock.method(console, "log", (s) => out.push(String(s)));
  try {
    assert.equal(await main(["privola-uvoz", csv]), 0);
    assert.ok(out.some((l) => l.includes("redak 3")));
    assert.ok(out.some((l) => l.includes("Upisano privola: 2")));
    assert.equal(await main(["privola-opozovi", "+385 98 123 4567"]), 0);
    assert.ok(out.some((l) => l.includes("Privola opozvana: +385981234567")));
    assert.equal(await main(["izvjestaj", "2026-09-30"]), 0);
    assert.ok(out.some((l) => l.includes("Izvještaj za 2026-09-30")));
    assert.equal(await main(["greska", "131047"]), 0);
    assert.ok(out.some((l) => l.startsWith("G-40")));
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
