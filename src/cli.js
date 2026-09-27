"use strict";
// Alat za postavljanje i dijagnostiku (poglavlja 2, 7 i 8).
//   npm run alat -- <naredba> [argumenti]

const fs = require("node:fs");
const { loadConfig, requireKeys } = require("./config");
const { Store } = require("./db");
const { WhatsAppClient, WhatsAppError } = require("./whatsapp");
const { ClinikoClient } = require("./cliniko");
const { describe, formatError } = require("./errors");
const { normalizePhone } = require("./phone");
const { formatDate, localDay, startOfLocalDay, iso, addHours } = require("./timeutil");

const HELP = `Naredbe (npm run alat -- <naredba>):

  provjera                      provjeri token, broj, pretplatu webhooka, predložak, Cliniko i webhook URL
  greska <kod>                  objasni kod greške iz Meta API-ja (npr. greska 131047)
  registriraj <PIN>             registriraj broj na Cloud API (korak 3.5, G-11)
  pretplati                     pretplati aplikaciju na WABA (korak 5.4, G-31)
  test-poruka <broj>            pošalji predložak na svoj mobitel s probnim podacima (korak 7)
  privola-dodaj <broj> <izvor>  upiši privolu (npr. privola-dodaj 0981234567 "obrazac pri naručivanju")
  privola-opozovi <broj>        opozovi privolu
  privola-uvoz <datoteka.csv>   upiši privole iz CSV-a: telefon;izvor;datum(neobavezno);cliniko_id(neobavezno)
  izvjestaj [GGGG-MM-DD]        dnevni izvještaj (zadano: danas)
`;

function ok(t) {
  console.log(`  ✔ ${t}`);
}
function bad(t) {
  console.log(`  ✘ ${t}`);
}
function warn(t) {
  console.log(`  ! ${t}`);
}

function waError(err) {
  return err instanceof WhatsAppError ? formatError(err.code, err.httpStatus) : err.message;
}

async function check(config) {
  let problems = 0;
  const fail = (t) => {
    problems++;
    bad(t);
  };

  console.log("Postavke (.env)");
  const needed = {
    WA_TOKEN: config.wa.token,
    WA_PHONE_NUMBER_ID: config.wa.phoneNumberId,
    WA_WABA_ID: config.wa.wabaId,
    WA_APP_SECRET: config.wa.appSecret,
    WA_VERIFY_TOKEN: config.wa.verifyToken,
    WA_GRAPH_VERSION: config.wa.graphVersion,
    CLINIKO_API_KEY: config.cliniko.apiKey,
    CLINIKO_USER_AGENT: config.cliniko.userAgent,
  };
  const missing = Object.keys(needed).filter((k) => !needed[k]);
  if (missing.length) fail(`Nedostaje: ${missing.join(", ")}`);
  else ok("Sve obavezne vrijednosti su upisane");
  if (config.wa.verifyToken && config.wa.verifyToken.length < 20) warn("WA_VERIFY_TOKEN je kratak – koristi dugi nasumični niz");
  if (!config.reception.user || !config.reception.password) warn("RECEPTION_USER/RECEPTION_PASSWORD nisu postavljeni – nema stranice /recepcija");

  if (config.wa.token && config.wa.phoneNumberId && config.wa.graphVersion) {
    const wa = new WhatsAppClient(config.wa);
    console.log("\nWhatsApp broj");
    try {
      const p = await wa.getPhoneNumber();
      ok(`${p.display_phone_number} – "${p.verified_name}"`);
      if (p.name_status && p.name_status !== "APPROVED") warn(`Prikazno ime: ${p.name_status} (G-02)`);
      if (p.quality_rating) (p.quality_rating === "GREEN" ? ok : warn)(`Kvaliteta: ${p.quality_rating}`);
      if (p.platform_type && p.platform_type !== "CLOUD_API") fail(`Broj nije registriran na Cloud API (${p.platform_type}) – npm run alat -- registriraj <PIN> (G-11)`);
    } catch (err) {
      fail(waError(err));
    }

    if (config.wa.wabaId) {
      console.log("\nPretplata aplikacije na WABA");
      try {
        const subs = await wa.getSubscribedApps();
        if ((subs.data || []).length) ok(`Pretplaćeno: ${subs.data.map((a) => a.whatsapp_business_api_data?.name || a.name || "aplikacija").join(", ")}`);
        else fail("Aplikacija NIJE pretplaćena – webhookovi neće stizati. npm run alat -- pretplati (G-31)");
      } catch (err) {
        fail(waError(err));
      }

      console.log(`\nPredložak "${config.template.name}" (${config.template.language})`);
      try {
        const res = await wa.getTemplates(config.template.name);
        const all = (res.data || []).filter((t) => t.name === config.template.name);
        const t = all.find((x) => x.language === config.template.language);
        if (!t) {
          const langs = all.map((x) => x.language).join(", ");
          fail(`Ne postoji s jezikom "${config.template.language}"${langs ? ` (postoje: ${langs})` : ""} (G-62)`);
        } else {
          (t.status === "APPROVED" ? ok : fail)(`Status: ${t.status}`);
          (t.category === "UTILITY" ? ok : warn)(`Kategorija: ${t.category}${t.category === "UTILITY" ? "" : " – treba biti UTILITY (G-61)"}`);
          const body = (t.components || []).find((c) => c.type === "BODY");
          const vars = new Set(((body && body.text) || "").match(/\{\{\d+\}\}/g) || []);
          (vars.size === 3 ? ok : fail)(`Varijabli u tijelu: ${vars.size} (treba 3: ime, datum, sat – G-63)`);
          const buttons = ((t.components || []).find((c) => c.type === "BUTTONS") || {}).buttons || [];
          const labels = buttons.map((b) => b.text);
          for (const want of [config.template.confirmLabel, config.template.changeLabel]) {
            if (labels.includes(want)) ok(`Gumb "${want}"`);
            else warn(`Nema gumba "${want}" (postoje: ${labels.join(", ") || "nijedan"}) – odgovori gumbom neće se prepoznati`);
          }
        }
      } catch (err) {
        fail(waError(err));
      }
    }
  }

  if (config.cliniko.apiKey && config.cliniko.userAgent) {
    console.log("\nCliniko");
    try {
      const cliniko = new ClinikoClient(config.cliniko);
      await cliniko.getUser();
      ok(`API ključ radi (${cliniko.base})`);
    } catch (err) {
      fail(err.message);
    }
  }

  if (config.publicWebhookUrl) {
    console.log(`\nWebhook ${config.publicWebhookUrl}`);
    if (!config.publicWebhookUrl.startsWith("https://")) fail("URL mora biti HTTPS (G-30)");
    try {
      const q = new URLSearchParams({ "hub.mode": "subscribe", "hub.verify_token": config.wa.verifyToken, "hub.challenge": "123" });
      const res = await fetch(`${config.publicWebhookUrl}?${q}`, { signal: AbortSignal.timeout(15000) });
      const text = await res.text();
      if (res.status === 200 && text === "123") ok("Verifikacija vraća challenge");
      else fail(`Verifikacija vratila HTTP ${res.status} "${text.slice(0, 60)}" – mora vratiti 123 (G-30)`);
    } catch (err) {
      fail(`Nedostupno: ${err.message} (certifikat? firewall? G-30)`);
    }
  } else {
    console.log("\nWebhook");
    warn("WEBHOOK_PUBLIC_URL nije upisan – javni webhook nije provjeren (G-30)");
  }

  console.log("\nLokalna baza");
  const store = new Store(config.dbPath);
  try {
    const consents = store.listConsents().filter((c) => !c.revoked_at).length;
    ok(`Aktivnih privola: ${consents}`);
    const last = store.lastJobRun("reminders");
    if (last) (last.error ? warn : ok)(`Zadnji prolaz podsjetnika: ${last.finished_at}${last.error ? ` – ${last.error}` : ""}`);
    else warn("Podsjetnici se još nisu pokrenuli (npm run podsjetnici -- --probno)");
    const tasks = store.openTasks().length;
    if (tasks) warn(`Otvorenih zadataka za recepciju: ${tasks}`);
  } finally {
    store.close();
  }

  console.log(problems ? `\nPronađeno problema: ${problems}` : "\nSve provjere prošle.");
  return problems ? 1 : 0;
}

function explain(code) {
  const n = Number(code);
  if (!Number.isInteger(n)) {
    console.log("Upiši broj, npr. npm run alat -- greska 131047");
    return 1;
  }
  const d = describe(n, null);
  console.log(formatError(n, null));
  console.log(d.temporary ? "[P] privremena – ima smisla ponoviti" : "[T] trajna – NE ponavljati isti zahtjev");
  return 0;
}

function parseCsv(text) {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  const sep = lines.some((l) => l.includes(";")) ? ";" : ",";
  return lines.map((l) => l.split(sep).map((c) => c.trim().replace(/^"(.*)"$/, "$1")));
}

function importConsents(store, file, now) {
  const rows = parseCsv(fs.readFileSync(file, "utf8"));
  let added = 0;
  rows.forEach((cols, i) => {
    const [rawPhone, source, date, patientId] = cols;
    const phone = normalizePhone(rawPhone);
    if (!phone) {
      if (i > 0) console.log(`  ! redak ${i + 1}: broj "${rawPhone}" nije ispravan – preskačem`);
      return;
    }
    if (!source) {
      console.log(`  ! redak ${i + 1}: nedostaje izvor privole – preskačem`);
      return;
    }
    const givenAt = /^\d{4}-\d{2}-\d{2}$/.test(date || "") ? `${date}T00:00:00.000Z` : iso(now);
    store.addConsent({ phone, patientId: patientId || null, source, givenAt });
    added++;
  });
  console.log(`Upisano privola: ${added}`);
}

function report(store, config, day) {
  const from = startOfLocalDay(day, config.timezone);
  const to = startOfLocalDay(localDay(addHours(from, 36), config.timezone), config.timezone);
  const r = store.dayReport(iso(from), iso(to));
  const by = Object.fromEntries(r.statuses.map((s) => [s.status, s.n]));
  const total = r.statuses.reduce((a, s) => a + s.n, 0);
  const replies = Object.fromEntries(r.replies.map((s) => [s.reply, s.n]));
  console.log(`Izvještaj za ${day}`);
  console.log(`  Podsjetnika poslano: ${total}`);
  console.log(`    pročitano ${by.read || 0}, isporučeno ${by.delivered || 0}, na putu ${(by.sent || 0) + (by.accepted || 0)}, NEUSPJELO ${by.failed || 0}`);
  console.log(`  Potvrdilo dolazak: ${replies.confirmed || 0}, traži promjenu: ${replies.change_requested || 0}`);
  console.log(`  Poruka od pacijenata: ${r.inbound}`);
  console.log(`  Prolaza posla: ${r.runs.runs}${r.runs.errors ? `, prekinutih: ${r.runs.errors}` : ""}`);
  if (!r.runs.runs) console.log("  ! Posao podsjetnika se taj dan nije pokrenuo (cron? G-87)");
}

async function main(argv) {
  const [cmd, ...args] = argv;
  const config = loadConfig();
  const now = new Date();

  switch (cmd) {
    case "provjera":
      return check(config);
    case "greska":
      return explain(args[0]);
    case "registriraj": {
      requireKeys(config, ["wa.token", "wa.phoneNumberId", "wa.graphVersion"]);
      if (!/^\d{6}$/.test(args[0] || "")) {
        console.log("PIN mora imati 6 znamenki: npm run alat -- registriraj 123456");
        return 1;
      }
      await new WhatsAppClient(config.wa).register(args[0]);
      console.log("Broj registriran na Cloud API. PIN spremi u upravitelj lozinki.");
      return 0;
    }
    case "pretplati":
      requireKeys(config, ["wa.token", "wa.wabaId", "wa.graphVersion"]);
      await new WhatsAppClient(config.wa).subscribeApp();
      console.log("Aplikacija pretplaćena na WABA. Provjeri: npm run alat -- provjera");
      return 0;
    case "test-poruka": {
      requireKeys(config, ["wa.token", "wa.phoneNumberId", "wa.graphVersion"]);
      const to = normalizePhone(args[0]);
      if (!to) {
        console.log("Upiši ispravan broj, npr. npm run alat -- test-poruka 0981234567");
        return 1;
      }
      const wamid = await new WhatsAppClient(config.wa).sendTemplate({
        to,
        name: config.template.name,
        language: config.template.language,
        bodyParams: ["Test Testić", formatDate(addHours(now, 24), config.timezone), "10:00"],
      });
      console.log(`Poslano (wamid ${wamid}). Na mobitelu provjeri poruku i gumbe; u logu servera status sent/delivered/read.`);
      return 0;
    }
    case "privola-dodaj":
    case "privola-opozovi":
    case "privola-uvoz":
    case "izvjestaj": {
      const store = new Store(config.dbPath);
      try {
        if (cmd === "izvjestaj") {
          const day = args[0] || localDay(now, config.timezone);
          if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
            console.log("Datum upiši kao GGGG-MM-DD");
            return 1;
          }
          report(store, config, day);
          return 0;
        }
        if (cmd === "privola-uvoz") {
          if (!args[0] || !fs.existsSync(args[0])) {
            console.log("Navedi postojeću CSV datoteku");
            return 1;
          }
          importConsents(store, args[0], now);
          return 0;
        }
        const phone = normalizePhone(args[0]);
        if (!phone) {
          console.log("Broj nije ispravan, npr. 0981234567 ili +385981234567");
          return 1;
        }
        if (cmd === "privola-opozovi") {
          console.log(store.revokeConsent(phone, iso(now)) ? `Privola opozvana: +${phone}` : `Nema aktivne privole za +${phone}`);
          return 0;
        }
        const source = args.slice(1).join(" ").trim();
        if (!source) {
          console.log('Navedi izvor privole, npr. privola-dodaj 0981234567 "obrazac pri naručivanju"');
          return 1;
        }
        store.addConsent({ phone, source, givenAt: iso(now) });
        console.log(`Privola upisana: +${phone}`);
        return 0;
      } finally {
        store.close();
      }
    }
    default:
      console.log(HELP);
      return cmd ? 1 : 0;
  }
}

if (require.main === module) {
  main(process.argv.slice(2)).then(
    (code) => {
      process.exitCode = code;
    },
    (err) => {
      console.error(`[GREŠKA] ${err instanceof WhatsAppError ? waError(err) : err.message}`);
      process.exitCode = 1;
    }
  );
}

module.exports = { main, parseCsv };
