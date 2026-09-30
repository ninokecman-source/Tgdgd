import { maskPhone } from './log.js';
import { todayIn, addDays, formatForTemplate, nowLocalString, zonedParts } from './time.js';

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

const MSG_STATUS_HR = { sent: '✓', delivered: '✓✓', read: 'pročitano', failed: 'NIJE ISPORUČENO' };
const WINDOW_MS = 24 * 3600_000;
const pad = (n) => String(n).padStart(2, '0');

function stamp(isoUtc, zone) {
  const p = zonedParts(new Date(isoUtc), zone);
  return `${p.day}.${p.month}. ${pad(p.hour)}:${pad(p.minute)}`;
}

/** WhatsApp dopušta slobodan odgovor samo 24 h nakon zadnje poruke pacijenta. */
export const canReply = (conv, now = Date.now()) => Boolean(conv) && now - Date.parse(conv.last_in_at) < WINDOW_MS;

/** Inbox: razgovori koji čekaju recepciju, s odgovorom unutar 24 h. */
function inboxHtml(db, zone, csrf, now) {
  const convs = db.openConversations();
  const hidden = (c) => `<input type="hidden" name="_csrf" value="${esc(csrf)}"><input type="hidden" name="phone" value="${esc(c.phone)}"><input type="hidden" name="seen" value="${esc(c.attention_id)}">`;
  const items = convs
    .map((c) => {
      const who = c.patient_name || c.profile_name || 'Nepoznat broj';
      const alias = c.patient_name && c.profile_name && c.profile_name !== c.patient_name ? ` <span class="muted">(WhatsApp: ${esc(c.profile_name)})</span>` : '';
      const thread = db
        .thread(c.phone)
        .map((m) => {
          const st = m.direction === 'out' ? ` <span class="${m.status === 'failed' ? 'err' : 'muted'}">${esc(MSG_STATUS_HR[m.status] || '')}${m.status === 'failed' && m.error ? ' – ' + esc(m.error) : ''}</span>` : '';
          return `<div class="msg ${m.direction}"><span class="muted">${esc(stamp(m.created_at, zone))}</span> ${esc(m.body)}${st}</div>`;
        })
        .join('');
      const reply = canReply(c, now)
        ? `<form method="post" action="/status/reply">${hidden(c)}<textarea name="text" rows="2" maxlength="4096" required placeholder="Odgovor pacijentu (bez zdravstvenih podataka)"></textarea><button>Pošalji</button></form>`
        : `<p class="err">Prošlo je više od 24 h od zadnje poruke pacijenta – WhatsApp više ne dopušta slobodan odgovor. Nazovite pacijenta.</p>`;
      return `<section class="conv"><div><strong>${esc(who)}</strong>${alias} · <a href="tel:+${esc(c.phone)}">+${esc(c.phone)}</a></div>
<div class="thread">${thread}</div>${reply}
<form method="post" action="/status/resolve">${hidden(c)}<button class="secondary">Riješeno</button></form></section>`;
    })
    .join('');
  return `<h2>Poruke pacijenata (${convs.length})</h2>${items || '<p class="muted">Nema neodgovorenih poruka.</p>'}`;
}

/**
 * Stranica za recepciju: poruke pacijenata (inbox), tko je dobio podsjetnik,
 * tko je potvrdio, koga treba nazvati.
 */
export function statusHtml(db, zone, { csrf = '', flash = '', now = Date.now() } = {}) {
  const open = db.openConversations().length;
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
<title>${open ? `(${open}) ` : ''}WhatsApp – Proprio Centar</title><style>
:root{--bg:#fafafa;--fg:#1d1d1f;--card:#fff;--head:#f0f0f0;--line:#e5e5e5;--warn:#fff4e5;--err:#b00020;--muted:#6b6b6b}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--card:#1f1f1f;--head:#2a2a2a;--line:#333;--warn:#3a2a10;--err:#ff8a80;--muted:#9a9a9a}}
body{font-family:system-ui,sans-serif;margin:16px;color:var(--fg);background:var(--bg)}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}h2::first-letter{text-transform:uppercase}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card);font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;white-space:nowrap}th{background:var(--head)}
tr.warn td{background:var(--warn)}.err{color:var(--err);font-size:12px;white-space:normal}.muted{color:var(--muted)}
.conv{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:10px 0}
.thread{margin:8px 0}.msg{padding:4px 8px;margin:3px 0;border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere}
.msg.in{background:var(--head)}.msg.out{background:var(--warn);margin-left:24px}
textarea{width:100%;box-sizing:border-box;font:inherit;padding:6px}form{margin:6px 0 0}button{font:inherit;padding:5px 12px}
.flash{background:var(--warn);padding:8px 12px;border-radius:6px}
</style></head><body><h1>WhatsApp – Proprio Centar</h1>
${flash ? `<p class="flash">${esc(flash)}</p>` : ''}${inboxHtml(db, zone, csrf, now)}
<h2>Podsjetnici</h2>
<p>Označeni redovi: podsjetnik nije poslan ili isporučen, ili pacijent traži promjenu – nazvati pacijenta.</p>${body}
<p class="muted">Osvježava se svaku minutu (osim dok pišete odgovor) · ${esc(nowLocalString(zone))}</p>
<script>
history.replaceState(null, '', '/status');
setInterval(() => {
  const busy = [...document.querySelectorAll('textarea')].some((t) => t.value.trim() || t === document.activeElement);
  if (!busy) location.reload();
}, 60000);
</script></body></html>`;
}
