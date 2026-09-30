import { maskPhone } from './log.js';
import { todayIn, addDays, formatForTemplate, nowLocalString } from './time.js';

const STATUS_HR = {
  sending: 'šalje se',
  sent: 'poslano',
  failed: 'NIJE POSLANO',
  skipped_no_phone: 'nema mobitela',
  skipped_no_consent: 'nema privole',
};
const DELIVERY_HR = { sent: 'poslano', delivered: 'isporučeno', read: 'pročitano', failed: 'NIJE ISPORUČENO' };
const REPLY_HR = { confirmed: '✅ potvrdio', change_requested: '🔁 traži promjenu', other: 'odgovorio' };

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

export function statusRows(db, zone, dates) {
  return db.forDates(dates).map((r) => ({
    datum: r.local_date,
    termin: formatForTemplate(r.starts_at, zone).sat,
    pacijent: r.patient_name,
    mobitel: maskPhone(r.phone),
    podsjetnik: STATUS_HR[r.status] || r.status,
    isporuka: r.status === 'sent' ? DELIVERY_HR[r.delivery] || '' : '',
    odgovor: REPLY_HR[r.reply] || '',
    greska: r.status === 'failed' || r.delivery === 'failed' ? `${r.error_code || ''} ${r.error_message || ''}`.trim() : '',
    problem: r.status !== 'sent' || r.delivery === 'failed' || r.reply === 'change_requested',
  }));
}

/** Stranica za recepciju: tko je dobio podsjetnik, tko je potvrdio, koga treba nazvati. */
export function statusHtml(db, zone) {
  const today = todayIn(zone);
  const dates = [today, addDays(today, 1), addDays(today, 2)];
  const rows = statusRows(db, zone, dates);
  const body = dates
    .map((d) => {
      const list = rows.filter((r) => r.datum === d);
      const title = formatForTemplate(`${d}T12:00:00Z`, zone).datum;
      if (!list.length) return `<h2>${esc(title)}</h2><p class="muted">Nema zapisa.</p>`;
      const tr = list
        .map((r) => `<tr class="${r.problem ? 'warn' : ''}"><td>${esc(r.termin)}</td><td>${esc(r.pacijent)}</td><td>${esc(r.mobitel)}</td><td>${esc(r.podsjetnik)}</td><td>${esc(r.isporuka)}</td><td>${esc(r.odgovor)}</td><td class="err">${esc(r.greska)}</td></tr>`)
        .join('');
      return `<h2>${esc(title)}</h2><div class="scroll"><table><thead><tr><th>Termin</th><th>Pacijent</th><th>Mobitel</th><th>Podsjetnik</th><th>Isporuka</th><th>Odgovor</th><th>Greška</th></tr></thead><tbody>${tr}</tbody></table></div>`;
    })
    .join('');
  return `<!doctype html><html lang="hr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300"><title>WhatsApp podsjetnici</title><style>
:root{--bg:#fafafa;--fg:#1d1d1f;--card:#fff;--head:#f0f0f0;--line:#e5e5e5;--warn:#fff4e5;--err:#b00020;--muted:#6b6b6b}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--card:#1f1f1f;--head:#2a2a2a;--line:#333;--warn:#3a2a10;--err:#ff8a80;--muted:#9a9a9a}}
body{font-family:system-ui,sans-serif;margin:16px;color:var(--fg);background:var(--bg)}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}h2::first-letter{text-transform:uppercase}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card);font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;white-space:nowrap}th{background:var(--head)}
tr.warn td{background:var(--warn)}.err{color:var(--err);font-size:12px;white-space:normal}.muted{color:var(--muted)}
</style></head><body><h1>WhatsApp podsjetnici – Proprio Centar</h1>
<p>Označeni redovi: podsjetnik nije poslan ili isporučen, ili pacijent traži promjenu – nazvati pacijenta.</p>${body}
<p class="muted">Osvježava se svakih 5 minuta · ${esc(nowLocalString(zone))}</p></body></html>`;
}
