import fs from 'node:fs';
import { normalizePhone } from './phone.js';

const norm = (s) => String(s ?? '').trim().toLowerCase();
const YES = new Set(['da', 'yes', 'true', '1', 'x', '✓', '✔', 'pristajem', 'pristaje']);

/**
 * Učitava datoteku privola (način "allowlist").
 * Svaki red: Cliniko ID pacijenta ILI broj mobitela. '#' = komentar.
 */
export function loadAllowlist(file) {
  const set = new Set();
  if (!file || !fs.existsSync(file)) return set;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const v = line.replace(/#.*/, '').trim();
    if (!v) continue;
    set.add(v);
    const phone = normalizePhone(v);
    if (phone) set.add(phone);
  }
  return set;
}

/**
 * Traži Cliniko prilagođeno polje pacijenta s imenom `fieldName`.
 * Podržava: potvrdni okvir (checkbox, jedna opcija), radio Da/Ne, tekst "Da".
 */
export function customFieldConsent(customFields, fieldName) {
  const target = norm(fieldName);
  for (const section of customFields?.sections || []) {
    if (section.archived) continue;
    for (const field of section.fields || []) {
      if (field.archived || norm(field.name) !== target) continue;
      if (Array.isArray(field.options) && field.options.length) {
        const selected = field.options.filter((o) => o.selected);
        if (!selected.length) return false;
        if (selected.some((o) => YES.has(norm(o.name)))) return true;
        // Checkbox s jednom opcijom (npr. "Pacijent pristaje") -> označeno = privola
        return field.options.length === 1;
      }
      return YES.has(norm(field.value));
    }
  }
  return false;
}

export function hasConsent(patient, phone, consentCfg, allowlist) {
  switch (consentCfg.mode) {
    case 'all':
      return true;
    case 'allowlist':
      return allowlist.has(String(patient.id)) || (phone && allowlist.has(phone));
    case 'custom_field':
      return customFieldConsent(patient.custom_fields, consentCfg.fieldName);
    default:
      return false;
  }
}
