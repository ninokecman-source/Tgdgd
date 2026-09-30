import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizePhone, isMobileNumber, pickMobile } from '../src/phone.js';
import { customFieldConsent, hasConsent } from '../src/consent.js';
import { dayRangeUtc, formatForTemplate, addDays, parseHours, todayIn } from '../src/time.js';
import { groupByPatient, targetDate } from '../src/reminders.js';
import { classifyReply } from '../src/webhook.js';
import { cleanParam } from '../src/whatsapp.js';

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
