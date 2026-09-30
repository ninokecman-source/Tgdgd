#!/usr/bin/env node
// Naredbe (pokretati iz mape projekta):
//   npm run check                                  – provjera veze s Clinikoom i WhatsAppom
//   npm run preview                                – što bi se poslalo sutra (NIŠTA ne šalje)
//   npm run preview -- --date=2026-10-01           – isto, za određeni dan
//   npm run send                                   – ručno slanje podsjetnika za sutra
//   npm run status -- --date=2026-10-01            – pregled zapisa za dan
import { loadEnvFile, loadConfig, assertConfig } from './config.js';
import { openDb } from './db.js';
import { ClinikoClient } from './cliniko.js';
import { WhatsAppClient } from './whatsapp.js';
import { runReminders, targetDate } from './reminders.js';
import { statusRows } from './status.js';

const [cmd, ...rest] = process.argv.slice(2);
const flags = Object.fromEntries(rest.map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));

async function check(cfg) {
  assertConfig(cfg, ['cliniko']);
  const cliniko = new ClinikoClient(cfg.cliniko);
  const user = await cliniko.currentUser();
  console.log(`✔ Cliniko: spojeno kao ${user.first_name ?? ''} ${user.last_name ?? ''} (${cliniko.baseUrl})`);

  try {
    assertConfig(cfg, ['whatsapp']);
  } catch (e) {
    console.log('✘ WhatsApp:', e.message);
    return;
  }
  const res = await fetch('https://waba-v2.360dialog.io/v1/configs/webhook', { headers: { 'D360-API-KEY': cfg.wa.d360ApiKey } });
  const text = await res.text();
  console.log(res.ok ? `✔ WhatsApp (360dialog): API ključ radi. Webhook: ${text}` : `✘ WhatsApp (360dialog): HTTP ${res.status} ${text}`);
}

async function main() {
  loadEnvFile();
  const cfg = loadConfig();
  switch (cmd) {
    case 'check':
      return check(cfg);

    case 'reminders': {
      const dryRun = Boolean(flags['dry-run']) || cfg.dryRun;
      assertConfig(cfg, dryRun ? ['cliniko'] : ['cliniko', 'whatsapp']);
      const db = openDb(cfg.dbPath);
      const s = await runReminders({
        cfg, db, dryRun,
        cliniko: new ClinikoClient(cfg.cliniko),
        wa: dryRun ? null : new WhatsAppClient(cfg.wa),
        date: typeof flags.date === 'string' ? flags.date : undefined,
      });
      console.log(`\nDatum: ${s.date} | termina: ${s.appointments} | pacijenata: ${s.patients}`);
      if (dryRun) {
        console.log('\nPROBNI PRIKAZ – ništa nije poslano:\n');
        for (const p of s.preview) {
          if (p.skip) console.log(`  – ${p.patient}: preskočeno (${p.skip})`);
          else console.log(`  ${p.alreadySent ? '(već poslano) ' : ''}${p.patient} -> ${p.to}: ime="${p.params[0]}", datum="${p.params[1]}", sat="${p.params[2]}"`);
        }
      } else {
        console.log(`Poslano: ${s.sent} | već poslano ranije: ${s.alreadySent} | greške: ${s.failed}`);
      }
      console.log(`Bez mobitela: ${s.noPhone} | bez privole: ${s.noConsent}`);
      return;
    }

    case 'status': {
      const db = openDb(cfg.dbPath);
      const date = typeof flags.date === 'string' ? flags.date : targetDate(cfg.timezone, 0);
      console.table(statusRows(db, cfg.timezone, [date]).map(({ problem, datum, ...r }) => r));
      return;
    }

    default:
      console.log('Naredbe: check | reminders [--dry-run] [--date=YYYY-MM-DD] | status [--date=YYYY-MM-DD]');
  }
}

main().catch((e) => {
  console.error('GREŠKA:', e.message);
  process.exit(1);
});
