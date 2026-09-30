import { nowLocalString } from './time.js';

const ts = () => nowLocalString(process.env.TIMEZONE || 'Europe/Zagreb');

export const log = {
  info: (...a) => console.log(`[${ts()}]`, ...a),
  warn: (...a) => console.warn(`[${ts()}] UPOZORENJE:`, ...a),
  error: (...a) => console.error(`[${ts()}] GREŠKA:`, ...a),
};

/** 385981234567 -> 38598***4567 (u logovima nema punih brojeva) */
export function maskPhone(p) {
  if (!p) return '-';
  const s = String(p);
  return s.length <= 7 ? '***' : s.slice(0, 5) + '***' + s.slice(-4);
}
