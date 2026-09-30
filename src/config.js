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
      d360ApiKey: env.D360_API_KEY || '',
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
    statusToken: env.STATUS_TOKEN || '',
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
  if (parts.includes('whatsapp') && !cfg.wa.d360ApiKey) missing.push('D360_API_KEY');
  // 360dialog ne potpisuje poruke: bez tajne putanje bilo tko tko pogodi adresu
  // mogao bi lažirati potvrde pacijenata.
  if (parts.includes('webhook') && !/^[A-Za-z0-9_-]{16,}$/.test(cfg.webhookPath.split('/').pop())) {
    missing.push('WEBHOOK_PATH (mora završavati dugim nasumičnim dijelom, npr. /whatsapp/webhook/ + rezultat naredbe "openssl rand -hex 16")');
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
