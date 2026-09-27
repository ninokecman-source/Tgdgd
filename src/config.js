"use strict";
// Postavke iz varijabli okruženja (.env). Tajne (token, App Secret, Cliniko
// ključ) postoje SAMO ovdje – nikad u kodu, gitu, logu ni frontendu (G-86).

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");

function loadEnvFile() {
  const envPath = process.env.ENV_FILE || path.join(ROOT, ".env");
  if (fs.existsSync(envPath)) process.loadEnvFile(envPath);
}

function int(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n)) throw new Error(`${name} mora biti broj, a glasi "${raw}"`);
  return n;
}

function str(name, fallback = "") {
  const raw = process.env[name];
  return raw === undefined || raw === "" ? fallback : raw.trim();
}

function list(name, fallback) {
  const raw = str(name, "");
  if (!raw) return fallback;
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

function parseHours(raw) {
  const m = /^(\d{1,2})\s*-\s*(\d{1,2})$/.exec(raw);
  if (!m) throw new Error(`SEND_HOURS mora biti u obliku "8-20", a glasi "${raw}"`);
  const start = Number(m[1]);
  const end = Number(m[2]);
  if (start < 0 || end > 24 || start >= end) {
    throw new Error(`SEND_HOURS "${raw}": početak mora biti manji od kraja, unutar 0-24`);
  }
  return { start, end };
}

function loadConfig() {
  loadEnvFile();
  return {
    wa: {
      token: str("WA_TOKEN"),
      phoneNumberId: str("WA_PHONE_NUMBER_ID"),
      wabaId: str("WA_WABA_ID"),
      appSecret: str("WA_APP_SECRET"),
      verifyToken: str("WA_VERIFY_TOKEN"),
      graphVersion: str("WA_GRAPH_VERSION"),
    },
    template: {
      name: str("WA_TEMPLATE_REMINDER", "podsjetnik_termin"),
      language: str("WA_TEMPLATE_LANGUAGE", "hr"),
      confirmLabel: str("WA_BUTTON_CONFIRM", "Potvrđujem"),
      changeLabel: str("WA_BUTTON_CHANGE", "Trebam promjenu"),
      nameFallback: str("WA_NAME_FALLBACK", "gospođo/gospodine"),
    },
    replies: {
      confirmed: str("REPLY_CONFIRMED", "Hvala, Vaš dolazak je potvrđen. Vidimo se!"),
      changeRequested: str(
        "REPLY_CHANGE",
        "Hvala na javljanju. Recepcija će Vas nazvati radi dogovora novog termina."
      ),
      optOut: str(
        "REPLY_STOP",
        "Odjavljeni ste s WhatsApp obavijesti Proprio Centra. Više Vam nećemo slati poruke ovim putem."
      ),
    },
    stopWords: list("STOP_WORDS", ["STOP", "ODJAVA", "ODJAVI"]).map((w) => w.toUpperCase()),
    cliniko: {
      apiKey: str("CLINIKO_API_KEY"),
      userAgent: str("CLINIKO_USER_AGENT"),
      businessId: str("CLINIKO_BUSINESS_ID"),
    },
    timezone: str("TIMEZONE", "Europe/Zagreb"),
    reminderHoursBefore: int("REMINDER_HOURS_BEFORE", 24),
    reminderMinHoursBefore: int("REMINDER_MIN_HOURS_BEFORE", 2),
    sendHours: parseHours(str("SEND_HOURS", "8-20")),
    maxSendAttempts: int("MAX_SEND_ATTEMPTS", 3),
    undeliveredAlertHours: int("UNDELIVERED_ALERT_HOURS", 4),
    retentionDays: int("RETENTION_DAYS", 365),
    dbPath: path.resolve(ROOT, str("DB_PATH", "data/whatsapp.sqlite3")),
    port: int("PORT", 3000),
    host: str("HOST", "127.0.0.1"),
    publicWebhookUrl: str("WEBHOOK_PUBLIC_URL"),
    reception: {
      user: str("RECEPTION_USER"),
      password: str("RECEPTION_PASSWORD"),
    },
    health: {
      maxJobAgeMinutes: int("HEALTH_MAX_JOB_AGE_MINUTES", 60),
      maxUnconfirmedMinutes: int("HEALTH_MAX_UNCONFIRMED_MINUTES", 30),
    },
  };
}

const LABELS = {
  "wa.token": "WA_TOKEN",
  "wa.phoneNumberId": "WA_PHONE_NUMBER_ID",
  "wa.wabaId": "WA_WABA_ID",
  "wa.appSecret": "WA_APP_SECRET",
  "wa.verifyToken": "WA_VERIFY_TOKEN",
  "wa.graphVersion": "WA_GRAPH_VERSION",
  "cliniko.apiKey": "CLINIKO_API_KEY",
  "cliniko.userAgent": "CLINIKO_USER_AGENT",
};

// Prekini s jasnom porukom ako nedostaje nešto bez čega dio sustava ne može raditi.
function requireKeys(config, keys) {
  const missing = keys.filter((k) => {
    const [a, b] = k.split(".");
    return !config[a] || !config[a][b];
  });
  if (missing.length) {
    const names = missing.map((k) => LABELS[k] || k).join(", ");
    throw new Error(`Nedostaje u .env: ${names} (vidi .env.example)`);
  }
  if (keys.includes("wa.graphVersion") && !/^v\d+\.\d+$/.test(config.wa.graphVersion)) {
    throw new Error(`WA_GRAPH_VERSION mora izgledati kao "v23.0", a glasi "${config.wa.graphVersion}"`);
  }
}

module.exports = { loadConfig, requireKeys, ROOT };
