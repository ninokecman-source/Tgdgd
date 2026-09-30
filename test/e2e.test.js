// Cijeli tok s lažnim (mock) Cliniko i WhatsApp serverima:
// dohvat termina -> privola -> slanje -> nema duplikata -> webhook statusi i odgovori.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadConfig } from '../src/config.js';
import { openDb } from '../src/db.js';
import { ClinikoClient } from '../src/cliniko.js';
import { WhatsAppClient } from '../src/whatsapp.js';
import { runReminders } from '../src/reminders.js';
import { createServer } from '../src/server.js';
import { statusHtml } from '../src/status.js';

const DAY = '2026-10-01';
let cliniko, wa, app, base;
const sent = [];
const patched = [];
let failNextFor = null; // broj za koji WhatsApp vraća grešku
let failAll = null; // { status, body } – greška za svaku poruku (npr. neispravan API ključ)

function listen(handler) {
  return new Promise((resolve) => {
    const s = http.createServer(handler).listen(0, '127.0.0.1', () => resolve(s));
  });
}
const readBody = (req) => new Promise((r) => { const c = []; req.on('data', (d) => c.push(d)); req.on('end', () => r(Buffer.concat(c).toString())); });
const json = (res, code, obj) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(obj)); };

const patients = {
  1: { id: 1, first_name: 'Ana', last_name: 'Anić', patient_phone_numbers: [{ phone_type: 'Mobile', number: '098 111 1111' }] },
  2: { id: 2, first_name: 'Ivan', preferred_first_name: 'Ivo', last_name: 'Ivić', patient_phone_numbers: [{ phone_type: 'Mobile', number: '+385 91 222 2222' }] },
  3: { id: 3, first_name: 'Bez', last_name: 'Mobitela', patient_phone_numbers: [{ phone_type: 'Home', number: '023 333 333' }] },
  4: { id: 4, first_name: 'Bez', last_name: 'Privole', patient_phone_numbers: [{ phone_type: 'Mobile', number: '099 444 4444' }] },
  5: { id: 5, first_name: 'Grupa', last_name: 'Član', patient_phone_numbers: [{ phone_type: 'Mobile', number: '095 555 5555' }] },
  6: { id: 6, first_name: 'Greška', last_name: 'Broj', patient_phone_numbers: [{ phone_type: 'Mobile', number: '097 666 6666' }] },
};

before(async () => {
  cliniko = await listen(async (req, res) => {
    const url = new URL(req.url, 'http://x');
    const self = `http://127.0.0.1:${cliniko.address().port}/v1`;
    assert.match(req.headers['user-agent'], /\(.+@.+\)/);
    assert.equal(req.headers.authorization, 'Basic ' + Buffer.from('TESTKEY-uk1:').toString('base64'));
    const q = url.searchParams.getAll('q[]');
    if (url.pathname === '/v1/individual_appointments') {
      assert.deepEqual(q, ['starts_at:>=2026-09-30T22:00:00Z', 'starts_at:<2026-10-01T22:00:00Z']);
      const page = url.searchParams.get('page') || '1';
      const mk = (id, pid, start, extra = {}) => ({ id, starts_at: start, patient: { links: { self: `${self}/patients/${pid}` } }, ...extra });
      if (page === '1') {
        return json(res, 200, {
          individual_appointments: [
            mk(101, 1, '2026-10-01T07:00:00Z'),
            mk(102, 1, '2026-10-01T12:00:00Z'), // drugi termin istog pacijenta – jedan podsjetnik
            mk(103, 2, '2026-10-01T13:30:00Z'),
            mk(104, 99, '2026-10-01T10:00:00Z', { cancelled_at: '2026-09-29T10:00:00Z' }), // otkazan
          ],
          links: { next: `${self}/individual_appointments?${url.searchParams.toString()}&page=2` },
        });
      }
      return json(res, 200, {
        individual_appointments: [mk(105, 3, '2026-10-01T08:00:00Z'), mk(106, 4, '2026-10-01T09:00:00Z'), mk(107, 6, '2026-10-01T15:00:00Z')],
        links: {},
      });
    }
    if (url.pathname === '/v1/group_appointments') {
      return json(res, 200, { group_appointments: [{ id: 201, starts_at: '2026-10-01T16:00:00Z' }], links: {} });
    }
    if (url.pathname === '/v1/group_appointments/201/attendees') {
      return json(res, 200, {
        attendees: [
          { id: 301, patient: { links: { self: `${self}/patients/5` } } },
          { id: 302, cancelled_at: '2026-09-30T08:00:00Z', patient: { links: { self: `${self}/patients/2` } } },
        ],
        links: {},
      });
    }
    const pm = /^\/v1\/patients\/(\d+)$/.exec(url.pathname);
    if (pm) return json(res, 200, patients[pm[1]]);
    const am = /^\/v1\/individual_appointments\/(\d+)$/.exec(url.pathname);
    if (am && req.method === 'GET') return json(res, 200, { id: am[1], notes: 'Stara napomena' });
    if (am && req.method === 'PATCH') {
      patched.push({ id: am[1], body: JSON.parse(await readBody(req)) });
      return json(res, 200, {});
    }
    json(res, 404, { error: 'not found' });
  });

  wa = await listen(async (req, res) => {
    assert.equal(req.headers['d360-api-key'], 'D360TEST');
    const body = JSON.parse(await readBody(req));
    if (failAll) return json(res, failAll.status, failAll.body);
    if (body.to === failNextFor) {
      return json(res, 400, { error: { code: 131026, message: 'Message undeliverable' } });
    }
    sent.push(body);
    json(res, 200, { messages: [{ id: `wamid.${sent.length}` }] });
  });
});

after(() => {
  cliniko.close();
  wa.close();
  app?.close();
});

function makeCtx(dbFile) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pwc-'));
  const consentFile = path.join(dir, 'consent.txt');
  fs.writeFileSync(consentFile, '# pilot\n1\n+385 91 222 2222\n3\n5\n6\n');
  const cfg = loadConfig({
    cliniko: { apiKey: 'TESTKEY-uk1', userAgent: 'Proprio test (test@proprio.hr)', baseUrl: `http://127.0.0.1:${cliniko.address().port}/v1`, includeGroup: true, writeNotes: true },
    wa: { d360ApiKey: 'D360TEST', baseUrl: `http://127.0.0.1:${wa.address().port}`, replyConfirm: 'Hvala!', replyChange: 'Javit ćemo se.' },
    consent: { mode: 'allowlist', file: consentFile },
    timezone: 'Europe/Zagreb',
    dbPath: dbFile || path.join(dir, 'test.db'),
    statusToken: 'stok',
    dryRun: false,
    testPhone: '',
  });
  return { cfg, db: openDb(cfg.dbPath), cliniko: new ClinikoClient(cfg.cliniko), wa: new WhatsAppClient(cfg.wa) };
}

let ctx;

test('probni prikaz (dry-run) ništa ne šalje', async () => {
  ctx = makeCtx();
  const s = await runReminders({ ...ctx, date: DAY, dryRun: true });
  assert.equal(sent.length, 0);
  assert.equal(s.patients, 6);
  const ana = s.preview.find((p) => p.patient === 'Ana Anić');
  assert.deepEqual(ana.params, ['Ana', 'četvrtak, 1. listopada', '09:00']);
  assert.equal(ctx.db.forDates([DAY]).length, 0);
});

test('slanje: privola, mobitel, grupni termin, greška', async () => {
  failNextFor = '385976666666';
  const s = await runReminders({ ...ctx, date: DAY });
  assert.equal(s.sent, 3, JSON.stringify(s)); // Ana, Ivo, Grupa Član
  assert.equal(s.failed, 1); // Greška Broj (131026)
  assert.equal(s.noPhone, 1); // fiksni broj
  assert.equal(s.noConsent, 1); // nije na popisu privola
  const toAna = sent.find((m) => m.to === '385981111111');
  assert.equal(toAna.template.name, 'podsjetnik_termin');
  assert.equal(toAna.template.language.code, 'hr');
  assert.deepEqual(toAna.template.components[0].parameters.map((p) => p.text), ['Ana', 'četvrtak, 1. listopada', '09:00']);
  const toIvo = sent.find((m) => m.to === '385912222222');
  assert.equal(toIvo.template.components[0].parameters[0].text, 'Ivo'); // preferred_first_name
  const grp = sent.find((m) => m.to === '385955555555');
  assert.equal(grp.template.components[0].parameters[2].text, '18:00');
});

test('ponovno pokretanje ne šalje duplikate; neuspjelo se ponovi', async () => {
  failNextFor = null;
  const before = sent.length;
  const s = await runReminders({ ...ctx, date: DAY });
  assert.equal(s.alreadySent, 3);
  assert.equal(s.sent, 1); // ponovni pokušaj za prethodno neuspjeli
  assert.equal(sent.length, before + 1);
  const s2 = await runReminders({ ...ctx, date: DAY });
  assert.equal(s2.sent, 0);
  assert.equal(s2.alreadySent, 4);
});

test('HTTP server: webhook, statusi, odgovori, stranica statusa', async () => {
  app = createServer(ctx);
  await new Promise((r) => app.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${app.address().port}`;

  // 360dialog šalje samo POST
  assert.equal((await fetch(`${base}/whatsapp/webhook`)).status, 405);

  const post = async (payload) => {
    const res = await fetch(`${base}/whatsapp/webhook`, { method: 'POST', body: JSON.stringify(payload), headers: { 'Content-Type': 'application/json' } });
    await ctx.pending;
    return res.status;
  };
  const anaRow = ctx.db.forDates([DAY]).find((x) => x.patient_name === 'Ana Anić');
  const ivoRow = ctx.db.forDates([DAY]).find((x) => x.patient_name === 'Ivan Ivić');

  // statusi: read pa delivered (obrnuti redoslijed) – ostaje read
  const st = (id, status) => ({ entry: [{ changes: [{ value: { statuses: [{ id, status, recipient_id: '385981111111' }] } }] }] });
  assert.equal(await post(st(anaRow.wamid, 'read')), 200);
  assert.equal(await post(st(anaRow.wamid, 'delivered')), 200);
  assert.equal(ctx.db.byWamid(anaRow.wamid).delivery, 'read');

  // gumb "Potvrđujem" (dvaput isti webhook – obradi se jednom)
  const before = sent.length;
  const btn = (id, from, ctxId, text) => ({ entry: [{ changes: [{ value: { messages: [{ id, from, type: 'button', context: { id: ctxId }, button: { text, payload: text } }] } }] }] });
  await post(btn('in.1', '385981111111', anaRow.wamid, 'Potvrđujem'));
  await post(btn('in.1', '385981111111', anaRow.wamid, 'Potvrđujem'));
  assert.equal(ctx.db.byWamid(anaRow.wamid).reply, 'confirmed');
  assert.equal(sent.length, before + 1); // automatski odgovor samo jednom
  assert.equal(sent.at(-1).text.body, 'Hvala!');
  // napomena upisana u oba Anina individualna termina
  assert.deepEqual(patched.map((p) => p.id).sort(), ['101', '102']);
  assert.equal(patched[0].body.notes, 'Stara napomena\n[WhatsApp] Pacijent potvrdio dolazak.');

  // slobodan tekst bez konteksta -> veže se na zadnji podsjetnik tog broja
  await post({ entry: [{ changes: [{ value: { messages: [{ id: 'in.2', from: '385912222222', type: 'text', text: { body: 'Ne mogu doći, trebam promjenu' } }] } }] }] });
  assert.equal(ctx.db.byWamid(ivoRow.wamid).reply, 'change_requested');
  assert.equal(ctx.db.byWamid(ivoRow.wamid).reply_text, null); // slobodan tekst se ne sprema

  // neuspjela isporuka
  await post({ entry: [{ changes: [{ value: { statuses: [{ id: ivoRow.wamid, status: 'failed', recipient_id: '385912222222', errors: [{ code: 131026, title: 'Message undeliverable' }] }] } }] }] });
  assert.equal(ctx.db.byWamid(ivoRow.wamid).delivery, 'failed');

  // stranica statusa
  assert.equal((await fetch(`${base}/status?token=krivo`)).status, 403);
  const html = statusHtml(ctx.db, 'Europe/Zagreb');
  assert.ok(html.includes('<html'));
  const rows = ctx.db.forDates([DAY]);
  assert.equal(rows.length, 6);
  assert.deepEqual(rows.map((x) => x.status).sort(), ['sent', 'sent', 'sent', 'sent', 'skipped_no_consent', 'skipped_no_phone']);
  assert.equal((await fetch(`${base}/health`)).status, 200);
});

test('premješten termin dobiva novi podsjetnik', async () => {
  const row = { reminder_key: '1|2026-10-01T09:00:00Z', patient_id: '1', patient_name: 'Ana Anić', phone: '385981111111', starts_at: '2026-10-01T09:00:00Z', local_date: DAY, appointments: '[]' };
  assert.equal(ctx.db.claim(row), true); // novo vrijeme = novi ključ
  assert.equal(ctx.db.claim(row), false);
});

test('greška računa (ključ, predložak) ne troši pokušaje; nakon popravka podsjetnici odu', async () => {
  const c = makeCtx();
  const before = sent.length;
  failAll = { status: 401, body: { meta: { success: false, http_code: 401, developer_message: 'Invalid api key' } } };
  for (let i = 0; i < 4; i++) {
    const s = await runReminders({ ...c, date: DAY });
    assert.equal(s.sent, 0);
    assert.equal(s.failed, 0);
    assert.equal(s.deferred, 4);
    assert.match(s.accountError, /401/);
  }
  failAll = { status: 404, body: { error: { code: 132001, message: 'Template name does not exist in the translation' } } };
  assert.equal((await runReminders({ ...c, date: DAY })).deferred, 4);
  failAll = null;
  const s = await runReminders({ ...c, date: DAY });
  assert.equal(s.sent, 4, JSON.stringify(s));
  assert.equal(s.accountError, null);
  assert.equal(sent.length, before + 4);
});
