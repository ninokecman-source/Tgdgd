import http from 'node:http';
import { pathToFileURL } from 'node:url';
import { loadEnvFile, loadConfig, assertConfig } from './config.js';
import { openDb } from './db.js';
import { ClinikoClient } from './cliniko.js';
import { WhatsAppClient } from './whatsapp.js';
import { runReminders } from './reminders.js';
import { handleWebhookRequest } from './webhook.js';
import { statusHtml } from './status.js';
import { zonedParts, ymd } from './time.js';
import { log } from './log.js';

const MAX_BODY = 2 * 1024 * 1024;
const STUCK_MS = 30 * 60_000;

/**
 * Stanje za uptime monitor: 503 ako zadnji krug slanja nije uspio (Cliniko,
 * ključ, predložak, ispad) ili ako slanje traje predugo. Greška jednog
 * pacijenta (npr. broj bez WhatsAppa) nije kvar servisa.
 */
export function healthStatus(ctx, now = Date.now()) {
  const problems = [];
  if (ctx.lastRun?.error) problems.push(`Zadnji krug slanja (${ctx.lastRun.at}): ${ctx.lastRun.error}`);
  if (ctx.runningSince && now - ctx.runningSince > STUCK_MS) problems.push('Slanje traje duže od 30 minuta – zapelo je');
  return { ok: problems.length === 0, problems, lastRun: ctx.lastRun || null };
}

export function createServer(ctx) {
  const { cfg } = ctx;
  return http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) req.destroy();
      else chunks.push(c);
    });
    req.on('end', () => {
      try {
        const body = Buffer.concat(chunks);
        const p = url.pathname.replace(/\/$/, '') || '/';
        if (p === cfg.webhookPath) return handleWebhookRequest(req, res, body, url, ctx);
        if (p === '/health') {
          const h = healthStatus(ctx);
          res.writeHead(h.ok ? 200 : 503, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
          return res.end(JSON.stringify(h));
        }
        if (p === '/status') {
          if (!cfg.statusToken || url.searchParams.get('token') !== cfg.statusToken) {
            res.writeHead(403);
            return res.end();
          }
          res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
          return res.end(statusHtml(ctx.db, cfg.timezone));
        }
        res.writeHead(404);
        res.end();
      } catch (e) {
        log.error('HTTP:', e.message);
        if (!res.headersSent) res.writeHead(500);
        res.end();
      }
    });
  });
}

/**
 * Jednostavan raspored: svake minute provjeri lokalno vrijeme; u svakom satu iz
 * REMINDER_HOURS pokreni slanje jednom. U 3 h noću obriši stare zapise.
 */
export function startScheduler(ctx, job, purge) {
  const { cfg } = ctx;
  const done = new Set();
  const tick = () => {
    const p = zonedParts(new Date(), cfg.timezone);
    const key = `${ymd(p)} ${p.hour}`;
    if (done.has(key)) return;
    if (cfg.hours.has(p.hour)) {
      done.add(key);
      job();
    } else if (p.hour === 3) {
      done.add(key);
      purge();
    }
    if (done.size > 200) done.clear();
  };
  tick();
  return setInterval(tick, 30_000);
}

async function main() {
  loadEnvFile();
  const cfg = loadConfig();
  assertConfig(cfg, ['cliniko', 'whatsapp', 'webhook']);
  const ctx = { cfg, db: openDb(cfg.dbPath), cliniko: new ClinikoClient(cfg.cliniko), wa: new WhatsAppClient(cfg.wa) };

  const job = async () => {
    if (ctx.runningSince) return;
    ctx.runningSince = Date.now();
    try {
      ctx.cliniko.patientCache.clear();
      const s = await runReminders(ctx);
      ctx.lastRun = {
        at: new Date().toISOString(), date: s.date, sent: s.sent, alreadySent: s.alreadySent, failed: s.failed,
        deferred: s.deferred, noPhone: s.noPhone, noConsent: s.noConsent, error: s.accountError,
      };
      log.info(`Podsjetnici za ${s.date}: poslano ${s.sent}, već ranije ${s.alreadySent}, greške pacijenta ${s.failed}, ` +
        `odgođeno ${s.deferred}, bez mobitela ${s.noPhone}, bez privole ${s.noConsent}`);
    } catch (e) {
      ctx.lastRun = { at: new Date().toISOString(), error: e.message };
      log.error('Slanje podsjetnika prekinuto:', e.message);
    } finally {
      ctx.runningSince = null;
    }
  };
  const purge = () => {
    const n = ctx.db.purgeOlderThan(new Date(Date.now() - cfg.retentionDays * 86400_000).toISOString());
    if (n) log.info(`Obrisano ${n} zapisa starijih od ${cfg.retentionDays} dana.`);
  };

  createServer(ctx).listen(cfg.port, () => {
    log.info(`Servis radi na portu ${cfg.port}. Webhook: ${cfg.webhookPath}. Slanje u satima: ${[...cfg.hours].join(',')} (${cfg.timezone}).` +
      (cfg.dryRun ? ' DRY_RUN – ništa se ne šalje.' : '') + (cfg.testPhone ? ' TEST_PHONE – sve poruke idu na testni broj.' : ''));
    startScheduler(ctx, job, purge);
  });

  const stop = () => {
    log.info('Zaustavljam servis.');
    ctx.db.close();
    process.exit(0);
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => {
    log.error(e.message);
    process.exit(1);
  });
}
