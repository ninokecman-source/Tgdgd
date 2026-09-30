import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizePhone, isMobileNumber, pickMobile } from '../src/phone.js';
import { customFieldConsent, hasConsent } from '../src/consent.js';
import { dayRangeUtc, formatForTemplate, addDays, parseHours, todayIn } from '../src/time.js';
import { groupByPatient, targetDate } from '../src/reminders.js';
import { classifyReply } from '../src/webhook.js';
import { loadConfig, assertConfig } from '../src/config.js';
import { cleanParam, isAccountError } from '../src/whatsapp.js';
import { openDb } from '../src/db.js';

test('normalizacija brojeva', () => {
  assert.equal(normalizePhone('098 123 4567'), '385981234567');
  assert.equal(normalizePhone('+385 98 123 4567'), '385981234567');
  assert.equal(normalizePhone('+385 0 98 123 4567'), '385981234567');
  assert.equal(normalizePhone('00385 91 234 567'), '38591234567');
  assert.equal(normalizePhone('(098) 123-4567'), '385981234567');
  assert.equal(normalizePhone('981234567'), '385981234567');
  assert.equal(normalizePhone('+49 170 1234567'), '491701234567');
  assert.equal(normalizePhone('123'), null);
  assert.equal(normalizePhone(''), null);
});

test('mobitel vs fiksni', () => {
  assert.ok(isMobileNumber('385981234567'));
  assert.ok(isMobileNumber('38591234567'));
  assert.ok(!isMobileNumber('38523123456')); // Zadar fiksni
  assert.equal(
    pickMobile({ patient_phone_numbers: [{ phone_type: 'Home', number: '023 123 456' }, { phone_type: 'Other', number: '099 765 4321' }] }),
    '385997654321',
  );
  assert.equal(pickMobile({ patient_phone_numbers: [{ phone_type: 'Home', number: '023 123 456' }] }), null);
  assert.equal(pickMobile({}), null);
});

test('privola iz Cliniko prilagođenog polja', () => {
  const cf = (field) => ({ sections: [{ name: 'Komunikacija', fields: [field] }] });
  assert.ok(customFieldConsent(cf({ name: 'WhatsApp podsjetnici', type: 'checkboxes', options: [{ name: 'Pacijent pristaje', selected: true }] }), 'whatsapp podsjetnici'));
  assert.ok(!customFieldConsent(cf({ name: 'WhatsApp podsjetnici', type: 'checkboxes', options: [{ name: 'Pacijent pristaje', selected: false }] }), 'WhatsApp podsjetnici'));
  assert.ok(customFieldConsent(cf({ name: 'WhatsApp podsjetnici', type: 'radiobuttons', options: [{ name: 'Da', selected: true }, { name: 'Ne' }] }), 'WhatsApp podsjetnici'));
  assert.ok(!customFieldConsent(cf({ name: 'WhatsApp podsjetnici', type: 'radiobuttons', options: [{ name: 'Da' }, { name: 'Ne', selected: true }] }), 'WhatsApp podsjetnici'));
  assert.ok(customFieldConsent(cf({ name: 'WhatsApp podsjetnici', type: 'single_line_text', value: 'da' }), 'WhatsApp podsjetnici'));
  assert.ok(!customFieldConsent(null, 'WhatsApp podsjetnici'));
  const allow = new Set(['111', '385981234567']);
  assert.ok(hasConsent({ id: 111 }, null, { mode: 'allowlist' }, allow));
  assert.ok(hasConsent({ id: 222 }, '385981234567', { mode: 'allowlist' }, allow));
  assert.ok(!hasConsent({ id: 333 }, '385991111111', { mode: 'allowlist' }, allow));
});

test('raspon dana u UTC, uključujući promjenu sata', () => {
  assert.deepEqual(dayRangeUtc('2026-10-01', 'Europe/Zagreb'), { fromUtc: '2026-09-30T22:00:00Z', toUtc: '2026-10-01T22:00:00Z' });
  // 25.10.2026. – prelazak na zimsko vrijeme (dan ima 25 sati)
  assert.deepEqual(dayRangeUtc('2026-10-25', 'Europe/Zagreb'), { fromUtc: '2026-10-24T22:00:00Z', toUtc: '2026-10-25T23:00:00Z' });
  // 29.3.2026. – prelazak na ljetno vrijeme (dan ima 23 sata)
  assert.deepEqual(dayRangeUtc('2026-03-29', 'Europe/Zagreb'), { fromUtc: '2026-03-28T23:00:00Z', toUtc: '2026-03-29T22:00:00Z' });
  assert.deepEqual(dayRangeUtc('2026-12-31', 'Europe/Zagreb'), { fromUtc: '2026-12-30T23:00:00Z', toUtc: '2026-12-31T23:00:00Z' });
});

test('hrvatski format datuma i sata', () => {
  assert.deepEqual(formatForTemplate('2026-10-01T12:30:00Z', 'Europe/Zagreb'), { datum: 'četvrtak, 1. listopada', sat: '14:30' });
  assert.deepEqual(formatForTemplate('2026-12-15T07:05:00Z', 'Europe/Zagreb'), { datum: 'utorak, 15. prosinca', sat: '08:05' });
});

test('datumi i sati', () => {
  assert.equal(addDays('2026-12-31', 1), '2027-01-01');
  assert.equal(targetDate('Europe/Zagreb', 1, new Date('2026-09-30T22:30:00Z')), '2026-10-02'); // već 1.10. u Zagrebu
  assert.equal(todayIn('Europe/Zagreb', new Date('2026-09-30T21:59:00Z')), '2026-09-30');
  assert.deepEqual([...parseHours('10-12,16')], [10, 11, 12, 16]);
});

test('jedan podsjetnik po pacijentu – najraniji termin', () => {
  const g = groupByPatient([
    { kind: 'individual', id: '1', startsAt: '2026-10-01T14:00:00Z', patientLink: 'https://x/v1/patients/7' },
    { kind: 'group', id: '2', attendeeId: '9', startsAt: '2026-10-01T08:00:00Z', patientLink: 'https://x/v1/patients/7' },
    { kind: 'individual', id: '3', startsAt: '2026-10-01T09:00:00Z', patientLink: 'https://x/v1/patients/8' },
  ]);
  assert.equal(g.length, 2);
  const p7 = g.find((x) => x.patientId === '7');
  assert.equal(p7.startsAt, '2026-10-01T08:00:00Z');
  assert.equal(p7.appointments.length, 2);
});

test('prepoznavanje odgovora', () => {
  const wa = { buttonConfirm: 'Potvrđujem', buttonChange: 'Trebam promjenu' };
  assert.equal(classifyReply('Potvrđujem', wa), 'confirmed');
  assert.equal(classifyReply('trebam promjenu', wa), 'change_requested');
  assert.equal(classifyReply('Moram otkazati, bolestan sam', wa), 'change_requested');
  assert.equal(classifyReply('Kolika je cijena?', wa), 'other');
  assert.equal(cleanParam('  Ana\n\tMarija   '), 'Ana Marija');
});

test('nijekanje nikad ne postaje potvrda', () => {
  const wa = { buttonConfirm: 'Potvrđujem', buttonChange: 'Trebam promjenu' };
  for (const t of ['Ne dolazim', 'Otkazujem, ne dolazim', 'Sutra ne dolazim, bolestan sam', 'Neću doći', 'necu doci', 'Ne mogu potvrditi dolazak', 'Ne stignem sutra']) {
    assert.equal(classifyReply(t, wa), 'change_requested', t);
  }
  for (const t of ['Dolazim', 'Doći ću', 'doci cu', 'potvrdujem', 'Dolazim, ali kasnim 10 minuta']) {
    assert.equal(classifyReply(t, wa), 'confirmed', t);
  }
  // nejasno -> recepcija pročita u aplikaciji
  for (const t of ['Dolazim, ne brinite', 'Ne znam hoću li doći', 'Nisam siguran']) {
    assert.equal(classifyReply(t, wa), 'other', t);
  }
});

test('webhook mora imati tajnu putanju (360dialog ne potpisuje poruke)', () => {
  const cfg = (webhookPath) => loadConfig({ webhookPath, wa: { d360ApiKey: 'k' }, cliniko: { apiKey: 'k', userAgent: 'x (a@b.hr)' } });
  const check = (p) => () => assertConfig(cfg(p), ['cliniko', 'whatsapp', 'webhook']);
  assert.throws(check('/whatsapp/webhook'), /WEBHOOK_PATH/);
  assert.throws(check('/whatsapp/webhook/kratko'), /WEBHOOK_PATH/);
  assert.doesNotThrow(check('/whatsapp/webhook/7f3c9a1e5b2d4c8f9e0a1b2c3d4e5f60'));
});

test('pokušaji: greška pacijenta 3 puta pa stop, novi broj ispočetka, greška računa se ne broji', () => {
  const db = openDb(':memory:');
  const row = { reminder_key: '6|2026-10-01T15:00:00Z', patient_id: '6', patient_name: 'Greška Broj', phone: '385976666666', starts_at: '2026-10-01T15:00:00Z', local_date: '2026-10-01', appointments: '[]' };
  for (let i = 0; i < 3; i++) {
    assert.equal(db.claim(row), true);
    db.markFailed(row.reminder_key, 131026, 'Message undeliverable');
  }
  assert.equal(db.claim(row), false);
  const fixed = { ...row, phone: '385976666667' }; // broj ispravljen u Clinikou
  assert.equal(db.claim(fixed), true);
  assert.equal(db.get(row.reminder_key).attempts, 1);
  for (let i = 0; i < 5; i++) {
    db.markDeferred(row.reminder_key, 401, 'Invalid api key');
    assert.equal(db.claim(fixed), true);
  }
  assert.equal(db.get(row.reminder_key).attempts, 1);
});

test('koje greške nisu do pacijenta', () => {
  const e = (code, httpStatus) => ({ code, httpStatus });
  for (const x of [e(401, 401), e(403, 403), e(132001, 404), e(131042, 400), e(130429, 429), e(131000, 500), e('NETWORK', 0), e(190, 401)]) {
    assert.ok(isAccountError(x), JSON.stringify(x));
  }
  for (const x of [e(131026, 400), e(131056, 400), e(131008, 400), e(132005, 400), e(100, 400)]) {
    assert.ok(!isAccountError(x), JSON.stringify(x));
  }
});

test('/health: greška zadnjeg kruga ili zapelo slanje = kvar', async () => {
  const { healthStatus } = await import('../src/server.js');
  const now = Date.parse('2026-10-01T10:00:00Z');
  assert.equal(healthStatus({}, now).ok, true); // tek pokrenut, još nije bilo kruga
  assert.equal(healthStatus({ lastRun: { at: 'x', sent: 3, failed: 1, error: null } }, now).ok, true); // greška pacijenta nije kvar
  const bad = healthStatus({ lastRun: { at: '2026-10-01T09:00:00Z', error: 'Cliniko API 401: Unauthorized' } }, now);
  assert.equal(bad.ok, false);
  assert.match(bad.problems[0], /Cliniko API 401/);
  assert.equal(healthStatus({ runningSince: now - 31 * 60_000 }, now).ok, false);
  assert.equal(healthStatus({ runningSince: now - 5 * 60_000 }, now).ok, true);
});
