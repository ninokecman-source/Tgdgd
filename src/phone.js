"use strict";
// Normalizacija broja prije slanja (poglavlje 3, G-41, G-84):
//   "098 123 4567" / "+385 98 123 4567" / "00385981234567" -> "385981234567"
// WhatsApp traži E.164 BEZ znaka '+'.

const { parsePhoneNumberFromString } = require("libphonenumber-js/max");

function normalizePhone(raw, defaultCountry = "HR") {
  if (raw === null || raw === undefined) return null;
  const text = String(raw).trim();
  if (!text) return null;
  const parsed = parsePhoneNumberFromString(text, defaultCountry);
  if (!parsed || !parsed.isValid()) return null;
  return parsed.number.replace(/^\+/, "");
}

function isMobile(normalized) {
  const parsed = parsePhoneNumberFromString(`+${normalized}`);
  if (!parsed) return false;
  const type = parsed.getType();
  return type === "MOBILE" || type === "FIXED_LINE_OR_MOBILE";
}

// U logove ide samo skraćeni broj (385981***67) – dovoljno za praćenje, a ne otkriva pacijenta.
function maskPhone(phone) {
  const s = String(phone || "");
  if (s.length <= 6) return "***";
  return `${s.slice(0, 6)}***${s.slice(-2)}`;
}

module.exports = { normalizePhone, isMobile, maskPhone };
