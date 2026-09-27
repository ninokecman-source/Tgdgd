"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { normalizePhone, isMobile, maskPhone } = require("../src/phone");
const { formatDate, formatTime, inSendingWindow, startOfLocalDay } = require("../src/timeutil");
const { describe, formatError } = require("../src/errors");
const { baseUrlForKey } = require("../src/cliniko");

test("normalizacija broja (poglavlje 3)", () => {
  assert.equal(normalizePhone("098 123 4567"), "385981234567");
  assert.equal(normalizePhone("+385 98 123 4567"), "385981234567");
  assert.equal(normalizePhone("00385981234567"), "385981234567");
  assert.equal(normalizePhone("(098) 123-4567"), "385981234567");
  assert.equal(normalizePhone("+44 7911 123456"), "447911123456");
  assert.equal(normalizePhone("123"), null);
  assert.equal(normalizePhone(""), null);
  assert.equal(normalizePhone(null), null);
});

test("mobilni vs fiksni broj", () => {
  assert.equal(isMobile("385981234567"), true);
  assert.equal(isMobile("38523123456"), false); // fiksni Zadar
});

test("maskiranje broja za log", () => {
  assert.equal(maskPhone("385981234567"), "385981***67");
});

test("datum i sat u zoni Europe/Zagreb, i ljeti i zimi (G-80)", () => {
  assert.equal(formatDate(new Date("2026-09-30T12:30:00Z"), "Europe/Zagreb"), "30.9.2026.");
  assert.equal(formatTime(new Date("2026-09-30T12:30:00Z"), "Europe/Zagreb"), "14:30");
  assert.equal(formatTime(new Date("2026-01-30T12:30:00Z"), "Europe/Zagreb"), "13:30");
  // Noć prijelaza na zimsko vrijeme (25.10.2026.)
  assert.equal(formatTime(new Date("2026-10-25T08:00:00Z"), "Europe/Zagreb"), "09:00");
  assert.equal(formatTime(new Date("2026-10-24T08:00:00Z"), "Europe/Zagreb"), "10:00");
});

test("vrijeme slanja se računa u lokalnoj zoni", () => {
  const hours = { start: 8, end: 20 };
  assert.equal(inSendingWindow(new Date("2026-09-30T05:59:00Z"), "Europe/Zagreb", hours), false); // 07:59
  assert.equal(inSendingWindow(new Date("2026-09-30T06:00:00Z"), "Europe/Zagreb", hours), true); // 08:00
  assert.equal(inSendingWindow(new Date("2026-09-30T18:00:00Z"), "Europe/Zagreb", hours), false); // 20:00
});

test("lokalna ponoć u UTC-u, i na dan promjene sata", () => {
  assert.equal(startOfLocalDay("2026-09-30", "Europe/Zagreb").toISOString(), "2026-09-29T22:00:00.000Z");
  assert.equal(startOfLocalDay("2026-03-29", "Europe/Zagreb").toISOString(), "2026-03-28T23:00:00.000Z");
  assert.equal(startOfLocalDay("2026-10-26", "Europe/Zagreb").toISOString(), "2026-10-25T23:00:00.000Z");
});

test("katalog grešaka: privremene, trajne i globalne", () => {
  assert.equal(describe(131047).ref, "G-40");
  assert.equal(describe(131047).temporary, false);
  assert.equal(describe(130429).temporary, true);
  assert.equal(describe(190).scope, "global");
  assert.equal(describe(131026).scope, "recipient");
  assert.equal(describe(132001).ref, "G-62");
  // nepoznat kod: 5xx je privremen, 4xx trajan
  assert.equal(describe(999999, 503).temporary, true);
  assert.equal(describe(999999, 400).temporary, false);
  assert.match(formatError(131026), /^G-41 \(131026\)/);
});

test("Cliniko shard iz API ključa", () => {
  assert.equal(baseUrlForKey("MS0xLWFiYw-eu1"), "https://api.eu1.cliniko.com/v1");
  assert.equal(baseUrlForKey("staristaromodni"), "https://api.cliniko.com/v1");
});
