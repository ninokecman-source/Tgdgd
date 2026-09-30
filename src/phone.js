/**
 * Pretvara broj iz Clinikoa u format koji traži WhatsApp: međunarodni, samo znamenke, bez '+'.
 *   "098 123 4567"      -> "385981234567"
 *   "+385 0 98 123 4567"-> "385981234567"  (suvišna nula se uklanja)
 *   "00385 98 ..."      -> "38598..."
 *   "+49 170 1234567"   -> "491701234567"   (strani brojevi ostaju kakvi jesu)
 * Vraća null ako broj očito nije valjan.
 */
export function normalizePhone(raw, countryCode = '385') {
  if (!raw) return null;
  const str = String(raw).trim();
  const hadPlus = str.startsWith('+');
  let s = str.replace(/\D/g, '');
  if (!s) return null;

  if (!hadPlus) {
    if (s.startsWith('00')) s = s.slice(2);
    else if (s.startsWith('0')) s = countryCode + s.slice(1);
    else if (!s.startsWith(countryCode) && s.length <= 9) s = countryCode + s;
  }
  // Česta greška: "+385 0 98..." -> ukloni nulu iza pozivnog broja
  if (s.startsWith(countryCode + '0')) s = countryCode + s.slice(countryCode.length + 1);
  if (s.length < 8 || s.length > 15) return null;
  if (s.startsWith('385') && !/^385\d{7,9}$/.test(s)) return null;
  return s;
}

/**
 * Hrvatski mobiteli: 091, 092, 095, 097, 098, 099 ... (385 9x + 6–7 znamenki).
 * Fiksni brojevi (npr. 023 Zadar) nisu mobitel -> nema WhatsAppa.
 * Za strane brojeve ne možemo znati vrstu pa ih prihvaćamo.
 */
export function isMobileNumber(n) {
  if (!n) return false;
  if (n.startsWith('385')) return /^3859[1-9]\d{6,7}$/.test(n);
  return true;
}

/**
 * Iz Cliniko pacijenta bira broj za WhatsApp:
 * prvo broj označen kao "Mobile", zatim bilo koji drugi koji je mobilni.
 */
export function pickMobile(patient) {
  const numbers = patient?.patient_phone_numbers || [];
  const isMob = (n) => String(n.phone_type || '').toLowerCase() === 'mobile';
  for (const n of [...numbers.filter(isMob), ...numbers.filter((n) => !isMob(n))]) {
    const norm = normalizePhone(n.number);
    if (norm && isMobileNumber(norm)) return norm;
  }
  return null;
}
