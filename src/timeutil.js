"use strict";
// Vrijeme (G-80): u bazi je sve u UTC-u, a datum, sat i "vrijeme slanja"
// računaju se u zoni klinike (Europe/Zagreb), pa prijelaz na ljetno/zimsko
// računanje vremena ne pomiče sat u poruci.

function parts(date, timeZone) {
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const out = {};
  for (const p of fmt.formatToParts(date)) out[p.type] = p.value;
  return out;
}

// "30.9.2026."
function formatDate(date, timeZone) {
  const p = parts(date, timeZone);
  return `${Number(p.day)}.${Number(p.month)}.${p.year}.`;
}

// "14:30"
function formatTime(date, timeZone) {
  const p = parts(date, timeZone);
  return `${p.hour}:${p.minute}`;
}

function localHour(date, timeZone) {
  return Number(parts(date, timeZone).hour);
}

// "2026-09-30" u lokalnoj zoni – za dnevni izvještaj.
function localDay(date, timeZone) {
  const p = parts(date, timeZone);
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}

// UTC trenutak lokalne ponoći za dan "2026-09-30" (za granice izvještaja).
function startOfLocalDay(day, timeZone) {
  const [y, m, d] = day.split("-").map(Number);
  const naive = Date.UTC(y, m - 1, d);
  const offsetAt = (ms) => {
    const p = parts(new Date(ms), timeZone);
    return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute)) - ms;
  };
  const first = naive - offsetAt(naive);
  return new Date(naive - offsetAt(first));
}

function inSendingWindow(date, timeZone, { start, end }) {
  const h = localHour(date, timeZone);
  return h >= start && h < end;
}

function iso(date) {
  return new Date(date).toISOString();
}

function addHours(date, hours) {
  return new Date(new Date(date).getTime() + hours * 3600 * 1000);
}

function addMinutes(date, minutes) {
  return new Date(new Date(date).getTime() + minutes * 60 * 1000);
}

module.exports = {
  formatDate,
  formatTime,
  localHour,
  localDay,
  startOfLocalDay,
  inSendingWindow,
  iso,
  addHours,
  addMinutes,
};
