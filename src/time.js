// Rad s vremenskim zonama bez vanjskih biblioteka (Intl API).
// Sva vremena u bazi i prema Clinikou su UTC; prikaz i "sutra" računaju se u Europe/Zagreb.

const partsFmt = new Map();
function fmtFor(zone) {
  if (!partsFmt.has(zone)) {
    partsFmt.set(zone, new Intl.DateTimeFormat('en-GB', {
      timeZone: zone, hourCycle: 'h23',
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
    }));
  }
  return partsFmt.get(zone);
}

/** Lokalni dijelovi datuma u zoni: { year, month, day, hour, minute, second } */
export function zonedParts(date, zone) {
  const p = Object.fromEntries(fmtFor(zone).formatToParts(date).filter((x) => x.type !== 'literal').map((x) => [x.type, Number(x.value)]));
  return { year: p.year, month: p.month, day: p.day, hour: p.hour, minute: p.minute, second: p.second };
}

/** Pomak zone u minutama za dani trenutak (Zagreb: +60 zimi, +120 ljeti). */
export function offsetMinutes(date, zone) {
  const p = zonedParts(date, zone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60000);
}

const pad = (n) => String(n).padStart(2, '0');
export const ymd = (p) => `${p.year}-${pad(p.month)}-${pad(p.day)}`;

export function parseYmd(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''));
  if (!m) throw new Error(`Neispravan datum: ${s} (očekujem YYYY-MM-DD)`);
  return { year: +m[1], month: +m[2], day: +m[3] };
}

export function addDays(dateStr, n) {
  const { year, month, day } = parseYmd(dateStr);
  const d = new Date(Date.UTC(year, month - 1, day + n));
  return ymd({ year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() });
}

/** Današnji datum u zoni, npr. "2026-09-30". */
export const todayIn = (zone, now = new Date()) => ymd(zonedParts(now, zone));

/** Lokalna ponoć zadanog dana kao UTC Date (ispravno i na dan promjene sata). */
export function localMidnightUtc(dateStr, zone) {
  const { year, month, day } = parseYmd(dateStr);
  const guess = Date.UTC(year, month - 1, day, 0, 0, 0);
  let t = guess - offsetMinutes(new Date(guess), zone) * 60000;
  t = guess - offsetMinutes(new Date(t), zone) * 60000;
  return new Date(t);
}

/** UTC ISO bez milisekundi, npr. "2026-10-01T12:30:00Z" (isti oblik kao Cliniko i baza). */
export const iso = (d) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');

/** { fromUtc, toUtc } za cijeli lokalni dan. */
export function dayRangeUtc(dateStr, zone) {
  return { fromUtc: iso(localMidnightUtc(dateStr, zone)), toUtc: iso(localMidnightUtc(addDays(dateStr, 1), zone)) };
}

/** Lokalni datum (YYYY-MM-DD) UTC trenutka. */
export const localDateOf = (utcIso, zone) => ymd(zonedParts(new Date(utcIso), zone));

const hrDate = new Map();
/** "2026-10-01T12:30:00Z" -> { datum: "četvrtak, 1. listopada", sat: "14:30" } */
export function formatForTemplate(utcIso, zone) {
  if (!hrDate.has(zone)) {
    hrDate.set(zone, {
      d: new Intl.DateTimeFormat('hr', { timeZone: zone, weekday: 'long', day: 'numeric', month: 'long' }),
      t: new Intl.DateTimeFormat('hr', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }),
    });
  }
  const f = hrDate.get(zone);
  const date = new Date(utcIso);
  return { datum: f.d.format(date), sat: f.t.format(date) };
}

/** "10-19" -> {10..19}; "9,13,17" -> {9,13,17}; "8-10,16" -> {8,9,10,16} */
export function parseHours(spec) {
  const out = new Set();
  for (const part of String(spec || '').split(',').map((s) => s.trim()).filter(Boolean)) {
    const [a, b] = part.split('-').map((x) => Number.parseInt(x, 10));
    const end = b === undefined ? a : b;
    if ([a, end].some((h) => Number.isNaN(h) || h < 0 || h > 23) || end < a) throw new Error(`Neispravni sati: ${spec}`);
    for (let h = a; h <= end; h++) out.add(h);
  }
  return out;
}

export function nowLocalString(zone, now = new Date()) {
  const p = zonedParts(now, zone);
  return `${ymd(p)} ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}
