"use strict";
// Klijent za WhatsApp Cloud API (Graph API). Samo ono što klinika treba:
// slanje predloška i slobodnog teksta, registracija broja, pretplata na
// webhook i dijagnostika.

const { describe } = require("./errors");

const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000];

class WhatsAppError extends Error {
  constructor({ message, code = null, httpStatus = null, subcode = null, details = null, traceId = null }) {
    super(message);
    this.name = "WhatsAppError";
    this.code = code;
    this.httpStatus = httpStatus;
    this.subcode = subcode;
    this.details = details;
    this.traceId = traceId;
    this.info = describe(code, httpStatus);
  }
}

// G-66: novi redovi, tabovi i višestruki razmaci u varijabli ruše predložak.
function cleanParam(value, maxLength = 200) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class WhatsAppClient {
  constructor({ token, phoneNumberId, wabaId, graphVersion, fetchImpl = fetch, sleepImpl = sleep, retryDelays = RETRY_DELAYS_MS }) {
    this.token = token;
    this.phoneNumberId = phoneNumberId;
    this.wabaId = wabaId;
    this.base = `https://graph.facebook.com/${graphVersion}`;
    this.fetch = fetchImpl;
    this.sleep = sleepImpl;
    this.retryDelays = retryDelays;
  }

  async request(method, pathAndQuery, body) {
    let res;
    try {
      res = await this.fetch(`${this.base}${pathAndQuery}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(30000),
      });
    } catch (err) {
      throw new WhatsAppError({ message: `Mrežna greška: ${err.message}` });
    }
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    if (!res.ok || (data && data.error)) {
      const e = (data && data.error) || {};
      throw new WhatsAppError({
        message: e.message || `HTTP ${res.status}`,
        code: e.code ?? null,
        httpStatus: res.status,
        subcode: e.error_subcode ?? null,
        details: e.error_data?.details ?? null,
        traceId: e.fbtrace_id ?? null,
      });
    }
    return data;
  }

  // Ponavlja samo privremene greške (poglavlje 4: 1 s, 2 s, 4 s, 8 s).
  async withRetry(fn) {
    for (let attempt = 0; ; attempt++) {
      try {
        return await fn();
      } catch (err) {
        const canRetry = err instanceof WhatsAppError && err.info.retryNow;
        if (!canRetry || attempt >= this.retryDelays.length) throw err;
        await this.sleep(this.retryDelays[attempt]);
      }
    }
  }

  async sendTemplate({ to, name, language, bodyParams }) {
    const payload = {
      messaging_product: "whatsapp",
      to,
      type: "template",
      template: {
        name,
        language: { code: language },
        components: [
          {
            type: "body",
            parameters: bodyParams.map((text) => ({ type: "text", text: cleanParam(text) })),
          },
        ],
      },
    };
    const data = await this.withRetry(() =>
      this.request("POST", `/${this.phoneNumberId}/messages`, payload)
    );
    return data.messages[0].id; // wamid
  }

  // Slobodan tekst – dopušten samo unutar 24 h od zadnje poruke pacijenta (G-40).
  async sendText({ to, body }) {
    const data = await this.withRetry(() =>
      this.request("POST", `/${this.phoneNumberId}/messages`, {
        messaging_product: "whatsapp",
        to,
        type: "text",
        text: { body },
      })
    );
    return data.messages[0].id;
  }

  register(pin) {
    return this.request("POST", `/${this.phoneNumberId}/register`, {
      messaging_product: "whatsapp",
      pin,
    });
  }

  subscribeApp() {
    return this.request("POST", `/${this.wabaId}/subscribed_apps`);
  }

  getSubscribedApps() {
    return this.request("GET", `/${this.wabaId}/subscribed_apps`);
  }

  getTemplates(name) {
    const q = new URLSearchParams({ name, fields: "name,language,status,category,components", limit: "100" });
    return this.request("GET", `/${this.wabaId}/message_templates?${q}`);
  }

  getPhoneNumber() {
    const q = new URLSearchParams({
      fields: "display_phone_number,verified_name,name_status,quality_rating,code_verification_status,platform_type",
    });
    return this.request("GET", `/${this.phoneNumberId}?${q}`);
  }
}

module.exports = { WhatsAppClient, WhatsAppError, cleanParam };
