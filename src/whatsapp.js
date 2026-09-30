const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class WhatsAppError extends Error {
  constructor(code, message, details, httpStatus) {
    super(`WhatsApp ${code}: ${message}${details ? ' – ' + details : ''}`);
    this.code = code;
    this.details = details;
    this.httpStatus = httpStatus;
  }
}

// Privremene greške – ima smisla ponoviti (vidi poglavlje 6 uputa)
const TRANSIENT = new Set([1, 2, 4, 80007, 130429, 131000, 131016, 131056, 133004, 135000]);
export const isTransient = (err) =>
  TRANSIENT.has(Number(err?.code)) || Number(err?.httpStatus) >= 500 || err?.name === 'TypeError';

// Greške računa, tokena, predloška, plaćanja, limita ili ispada servisa – pogodile bi
// svakog pacijenta, pa mu ne troše pokušaje (katalog grešaka, poglavlje 6 uputa).
// 131056 (previše poruka istom broju) je vezana uz pacijenta.
const ACCOUNT = new Set([10, 190, 200, 368, 131005, 131031, 131042, 131048, 131051, 132000, 132001, 132012, 132015, 132016, 133010, 80007, 130429]);
export const isAccountError = (err) =>
  ACCOUNT.has(Number(err?.code)) ||
  [401, 403].includes(Number(err?.httpStatus)) ||
  err?.code === 'NETWORK' ||
  (isTransient(err) && Number(err?.code) !== 131056);

/** Čisti vrijednost varijable predloška (greška 132007: novi redovi, tabovi, >4 razmaka). */
export const cleanParam = (v) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, 200);

export class WhatsAppClient {
  constructor(wa) {
    this.wa = wa;
    const base = wa.baseUrl || 'https://graph.facebook.com';
    this.url = `${base}/${wa.graphVersion}/${wa.phoneNumberId}/messages`;
    this.headers = { Authorization: `Bearer ${wa.token}` };
  }

  async send(payload) {
    let res;
    try {
      res = await fetch(this.url, {
        method: 'POST',
        headers: { ...this.headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ messaging_product: 'whatsapp', recipient_type: 'individual', ...payload }),
        signal: AbortSignal.timeout(30_000),
      });
    } catch (e) {
      throw new WhatsAppError('NETWORK', e.message, null, 0);
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) {
      const e = data.error || {};
      throw new WhatsAppError(e.code ?? res.status, e.message || res.statusText, e.error_data?.details, res.status);
    }
    const id = data.messages?.[0]?.id;
    if (!id) throw new WhatsAppError('NO_ID', 'Odgovor bez ID-a poruke', JSON.stringify(data).slice(0, 200), res.status);
    return id;
  }

  /** Slanje s ponavljanjem za privremene greške (1 s, 4 s, 16 s). */
  async sendWithRetry(payload, attempts = 3) {
    for (let i = 0; ; i++) {
      try {
        return await this.send(payload);
      } catch (err) {
        const transient = isTransient(err) || err.code === 'NETWORK';
        if (!transient || i >= attempts - 1) throw err;
        await sleep(1000 * 4 ** i);
      }
    }
  }

  sendTemplate(to, bodyParams) {
    return this.sendWithRetry({
      to,
      type: 'template',
      template: {
        name: this.wa.templateName,
        language: { code: this.wa.templateLang },
        components: [
          { type: 'body', parameters: bodyParams.map((t) => ({ type: 'text', text: cleanParam(t) })) },
        ],
      },
    });
  }

  sendText(to, text) {
    return this.sendWithRetry({ to, type: 'text', text: { preview_url: false, body: text } });
  }
}
