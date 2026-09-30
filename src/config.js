import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseHours } from './time.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Učitava .env iz mape projekta (ugrađeno u Node.js, bez dotenv-a). */
export function loadEnvFile(file = process.env.ENV_FILE || path.join(ROOT, '.env')) {
  if (fs.existsSync(file)) process.loadEnvFile(file);
}

const bool = (v, def = false) =>
  v === undefined || v === '' ? def : ['1', 'true', 'da', 'yes'].includes(String(v).toLowerCase());
const int = (v, def) => (v === undefined || v === '' ? def : Number.parseInt(v, 10));
const rel = (p) => (path.isAbsolute(p) || p === ':memory:' ? p : path.join(ROOT, p));

export function loadConfig(overrides = {}) {
  const env = process.env;
  const cfg = {
    cliniko: {
      apiKey: env.CLINIKO_API_KEY || '',
      userAgent: env.CLINIKO_USER_AGENT || '',
      baseUrl: env.CLINIKO_BASE_URL || '', // samo za testove
      includeGroup: bool(env.CLINIKO_INCLUDE_GROUP, true),
      writeNotes: bool(env.CLINIKO_WRITE_NOTES, false),
    },
    wa: {
      token: env.WA_TOKEN || '',
      phoneNumberId: env.WA_PHONE_NUMBER_ID || '',
      graphVersion: env.WA_GRAPH_VERSION || 'v23.0',
      appSecret: env.WA_APP_SECRET || '',
      verifyToken: env.WA_VERIFY_TOKEN || '',
      baseUrl: env.WA_BASE_URL || '', // samo za testove
      templateName: env.WA_TEMPLATE_NAME || 'podsjetnik_termin',
      templateLang: env.WA_TEMPLATE_LANG || 'hr',
      buttonConfirm: env.WA_BUTTON_CONFIRM || 'Potvrđujem',
      buttonChange: env.WA_BUTTON_CHANGE || 'Trebam promjenu',
      replyConfirm: env.WA_REPLY_CONFIRM ?? '',
      replyChange: env.WA_REPLY_CHANGE ?? '',
    },
    consent: {
      mode: (env.CONSENT_MODE || 'allowlist').toLowerCase(),
      fieldName: env.CONSENT_FIELD_NAME || 'WhatsApp podsjetnici',
      file: rel(env.CONSENT_FILE || './consent.txt'),
    },
    timezone: env.TIMEZONE || 'Europe/Zagreb',
    daysAhead: int(env.REMINDER_DAYS_AHEAD, 1),
    hours: parseHours(env.REMINDER_HOURS || '10-19'),
    port: int(env.PORT, 3000),
    webhookPath: (env.WEBHOOK_PATH || '/whatsapp/webhook').replace(/\/$/, ''),
    receptionPassword: env.RECEPTION_PASSWORD || '',
    dbPath: rel(env.DB_PATH || './data/proprio-whatsapp.db'),
    retentionDays: int(env.RETENTION_DAYS, 90),
    dryRun: bool(env.DRY_RUN, false),
    testPhone: env.TEST_PHONE || '',
  };
  return deepMerge(cfg, overrides);
}

/** Provjera da su postavljene varijable potrebne za određeni dio sustava. */
export function assertConfig(cfg, parts) {
  const missing = [];
  if (parts.includes('cliniko')) {
    if (!cfg.cliniko.apiKey) missing.push('CLINIKO_API_KEY');
    if (!/\(.+@.+\)/.test(cfg.cliniko.userAgent)) missing.push('CLINIKO_USER_AGENT (mora sadržavati e-mail u zagradama)');
  }
  if (parts.includes('whatsapp')) {
    if (!cfg.wa.token) missing.push('WA_TOKEN');
    if (!cfg.wa.phoneNumberId) missing.push('WA_PHONE_NUMBER_ID');
  }
  if (parts.includes('webhook')) {
    // Bez App Secreta ne može se provjeriti potpis, pa bi bilo tko mogao lažirati odgovore pacijenata.
    if (!cfg.wa.appSecret) missing.push('WA_APP_SECRET');
    if (cfg.wa.verifyToken.length < 16) missing.push('WA_VERIFY_TOKEN (dugi nasumični niz, npr. rezultat naredbe "openssl rand -hex 16")');
  }
  if (!['custom_field', 'allowlist', 'all'].includes(cfg.consent.mode)) {
    missing.push('CONSENT_MODE (custom_field, allowlist ili all)');
  }
  if (missing.length) {
    throw new Error('Nedostaju ili su neispravne postavke u .env:\n  - ' + missing.join('\n  - '));
  }
}

function deepMerge(target, src) {
  for (const [k, v] of Object.entries(src || {})) {
    if (v && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Set)) target[k] = deepMerge(target[k] || {}, v);
    else target[k] = v;
  }
  return target;
}
