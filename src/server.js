"use strict";
// Webhook server (korak 5, poglavlje 4) + inbox recepcije + provjera zdravlja.
// Pokretanje: npm start

const express = require("express");
const { verifySignature, processPendingEvents } = require("./webhook");
const { mountReception } = require("./reception");
const { iso, addMinutes } = require("./timeutil");

function healthStatus({ store, config, now }) {
  const n = now();
  const problems = [];
  const last = store.lastJobRun("reminders");
  if (!last) {
    problems.push("Posao podsjetnika se još nije pokrenuo");
  } else if (new Date(last.finished_at) < addMinutes(n, -config.health.maxJobAgeMinutes)) {
    problems.push(`Posao podsjetnika nije se pokrenuo od ${last.finished_at} (cron? G-87)`);
  } else if (last.error) {
    problems.push(`Zadnji prolaz podsjetnika prekinut: ${last.error}`);
  }
  const unconfirmed = store.countUnconfirmedBefore(iso(addMinutes(n, -config.health.maxUnconfirmedMinutes)));
  if (unconfirmed) {
    problems.push(`${unconfirmed} poslanih poruka bez ijednog statusa s webhooka – provjeri webhook (G-31, G-35)`);
  }
  return {
    ok: problems.length === 0,
    problems,
    lastReminderRun: last ? last.finished_at : null,
    lastWebhookAt: store.getKv("last_webhook_at"),
  };
}

function createApp(ctx) {
  const { config, store, log } = ctx;
  const app = express();
  app.disable("x-powered-by");
  app.set("trust proxy", "loopback");

  // 1) Verifikacija webhooka (Meta šalje GET) – G-30: vrati čisti challenge.
  app.get("/whatsapp/webhook", (req, res) => {
    const mode = req.query["hub.mode"];
    const token = req.query["hub.verify_token"];
    const challenge = req.query["hub.challenge"];
    if (mode === "subscribe" && config.wa.verifyToken && token === config.wa.verifyToken && typeof challenge === "string") {
      return res.status(200).type("text/plain").send(challenge);
    }
    log.warn("Webhook verifikacija odbijena: verify token se ne podudara (G-30)");
    return res.sendStatus(403);
  });

  // 2) Događaji (Meta šalje POST). Sirovo tijelo zbog potpisa (G-32); događaj
  //    se sprema, odmah se vraća 200 (G-33), obrada ide nakon toga.
  app.post("/whatsapp/webhook", express.raw({ type: () => true, limit: "2mb" }), (req, res) => {
    const raw = Buffer.isBuffer(req.body) ? req.body : Buffer.alloc(0);
    if (!verifySignature(raw, req.get("X-Hub-Signature-256"), config.wa.appSecret)) {
      log.warn("Webhook: neispravan potpis – odbijeno (G-32)");
      return res.sendStatus(401);
    }
    const text = raw.toString("utf8");
    try {
      JSON.parse(text);
    } catch {
      return res.sendStatus(400);
    }
    store.storeEvent(text, iso(ctx.now()));
    res.sendStatus(200);
    setImmediate(() => processPendingEvents(ctx).catch((err) => log.error(`Obrada webhooka: ${err.message}`)));
  });

  // Za uptime monitor (G-87): 503 kad nešto ne radi.
  app.get("/zdravlje", (req, res) => {
    const h = healthStatus(ctx);
    res.status(h.ok ? 200 : 503).json(h);
  });

  if (config.reception.user && config.reception.password) {
    mountReception(app, ctx);
  }

  return app;
}

function main() {
  const { loadConfig, requireKeys } = require("./config");
  const { Store } = require("./db");
  const { WhatsAppClient } = require("./whatsapp");
  const { createLogger } = require("./log");

  const config = loadConfig();
  requireKeys(config, ["wa.token", "wa.phoneNumberId", "wa.appSecret", "wa.verifyToken", "wa.graphVersion"]);
  const log = createLogger();
  const ctx = {
    config,
    log,
    store: new Store(config.dbPath),
    wa: new WhatsAppClient(config.wa),
    now: () => new Date(),
  };
  const app = createApp(ctx);
  const server = app.listen(config.port, config.host, () => {
    log.info(`Webhook server sluša na ${config.host}:${config.port}`);
    if (!config.reception.user || !config.reception.password) {
      log.warn("RECEPTION_USER/RECEPTION_PASSWORD nisu postavljeni – stranica /recepcija je isključena");
    }
    // Događaji spremljeni prije pada servera obrađuju se odmah po pokretanju.
    processPendingEvents(ctx).catch((err) => log.error(`Obrada webhooka: ${err.message}`));
  });

  const stop = () => server.close(() => {
    ctx.store.close();
    process.exit(0);
  });
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    console.error(`[GREŠKA] ${err.message}`);
    process.exitCode = 1;
  }
}

module.exports = { createApp, healthStatus };
