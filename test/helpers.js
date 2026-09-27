"use strict";

const { Store } = require("../src/db");
const { silentLogger } = require("../src/log");

function makeConfig(overrides = {}) {
  return {
    wa: {
      token: "tok",
      phoneNumberId: "PNID",
      wabaId: "WABA",
      appSecret: "app-secret",
      verifyToken: "verify-token-dugi-nasumicni-niz",
      graphVersion: "v23.0",
    },
    template: {
      name: "podsjetnik_termin",
      language: "hr",
      confirmLabel: "Potvrđujem",
      changeLabel: "Trebam promjenu",
      nameFallback: "gospođo/gospodine",
    },
    replies: { confirmed: "Hvala, potvrđeno.", changeRequested: "Nazvat ćemo Vas.", optOut: "Odjavljeni ste." },
    stopWords: ["STOP", "ODJAVA"],
    cliniko: { apiKey: "k-eu1", userAgent: "test", businessId: "" },
    timezone: "Europe/Zagreb",
    reminderHoursBefore: 24,
    reminderMinHoursBefore: 2,
    sendHours: { start: 8, end: 20 },
    maxSendAttempts: 3,
    undeliveredAlertHours: 4,
    retentionDays: 365,
    dbPath: ":memory:",
    port: 0,
    host: "127.0.0.1",
    publicWebhookUrl: "",
    reception: { user: "recepcija", password: "tajna" },
    health: { maxJobAgeMinutes: 60, maxUnconfirmedMinutes: 30 },
    ...overrides,
  };
}

function makeStore() {
  return new Store(":memory:");
}

// Lažni WhatsApp klijent: bilježi poslano, po želji baca zadane greške.
function fakeWa({ failWith = [] } = {}) {
  const sent = [];
  let n = 0;
  return {
    sent,
    failWith,
    async sendTemplate(args) {
      if (this.failWith.length) throw this.failWith.shift();
      sent.push({ kind: "template", ...args });
      return `wamid.T${++n}`;
    },
    async sendText(args) {
      sent.push({ kind: "text", ...args });
      return `wamid.X${++n}`;
    },
  };
}

function fakeCliniko({ appointments = [], patients = {} } = {}) {
  const calls = { list: 0, get: 0, patient: 0 };
  return {
    calls,
    appointments,
    patients,
    async listAppointments(from, to) {
      calls.list++;
      return this.appointments.filter((a) => new Date(a.startsAt) >= from && new Date(a.startsAt) < to);
    },
    async getAppointment(id) {
      calls.get++;
      return this.appointments.find((a) => a.id === id) || null;
    },
    async getPatient(id) {
      calls.patient++;
      return this.patients[id] || null;
    },
  };
}

function appt(id, startsAt, patientId = "p1", extra = {}) {
  return { id, startsAt, cancelled: false, archived: false, didNotArrive: false, patientId, businessId: "b1", ...extra };
}

module.exports = { makeConfig, makeStore, fakeWa, fakeCliniko, appt, log: silentLogger };
