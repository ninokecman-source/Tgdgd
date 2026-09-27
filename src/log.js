"use strict";
// Jednostavan log s vremenom. Bez sadržaja poruka, bez zdravstvenih podataka
// i bez tokena (poglavlje 4 i G-86); brojevi se maskiraju prije poziva.

function createLogger(stream = process.stdout, errStream = process.stderr) {
  const line = (s, prefix, text) => s.write(`${new Date().toISOString()} ${prefix}${text}\n`);
  return {
    info: (t) => line(stream, "", t),
    warn: (t) => line(stream, "[!] ", t),
    error: (t) => line(errStream, "[GREŠKA] ", t),
  };
}

const silentLogger = { info() {}, warn() {}, error() {} };

module.exports = { createLogger, silentLogger };
