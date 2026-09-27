"use strict";
// Izvor termina: Cliniko API (samo čitanje). Dohvaća se isključivo ono što
// treba za podsjetnik – vrijeme termina, ime i broj pacijenta. Dijagnoze,
// bilješke i vrsta terapije se ne dohvaćaju (poglavlje 5).

class ClinikoError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ClinikoError";
    this.status = status;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function idFromLink(obj, kind) {
  const href = obj?.links?.self || "";
  const m = new RegExp(`/${kind}/(\\d+)`).exec(href);
  return m ? m[1] : null;
}

function baseUrlForKey(apiKey) {
  // Ključ završava oznakom sharda (npr. "...-eu1"); stari ključevi je nemaju.
  const m = /-([a-z]{2}\d+)$/.exec(apiKey || "");
  return m ? `https://api.${m[1]}.cliniko.com/v1` : "https://api.cliniko.com/v1";
}

function toAppointment(a) {
  return {
    id: String(a.id),
    startsAt: a.starts_at,
    cancelled: Boolean(a.cancelled_at),
    archived: Boolean(a.archived_at || a.deleted_at),
    didNotArrive: Boolean(a.did_not_arrive),
    patientId: idFromLink(a.patient, "patients"),
    businessId: idFromLink(a.business, "businesses"),
  };
}

class ClinikoClient {
  constructor({ apiKey, userAgent, fetchImpl = fetch, sleepImpl = sleep }) {
    this.base = baseUrlForKey(apiKey);
    this.auth = `Basic ${Buffer.from(`${apiKey}:`).toString("base64")}`;
    this.userAgent = userAgent;
    this.fetch = fetchImpl;
    this.sleep = sleepImpl;
  }

  async get(urlOrPath, { allow404 = false } = {}) {
    const url = urlOrPath.startsWith("http") ? urlOrPath : `${this.base}${urlOrPath}`;
    for (let attempt = 0; attempt < 4; attempt++) {
      let res;
      try {
        res = await this.fetch(url, {
          headers: { Authorization: this.auth, Accept: "application/json", "User-Agent": this.userAgent },
          signal: AbortSignal.timeout(30000),
        });
      } catch (err) {
        if (attempt === 3) throw new ClinikoError(`Cliniko nedostupan: ${err.message}`, null);
        await this.sleep(1000 * 2 ** attempt);
        continue;
      }
      if (res.status === 404 && allow404) return null;
      if (res.status === 429 || res.status >= 500) {
        if (attempt === 3) throw new ClinikoError(`Cliniko HTTP ${res.status}`, res.status);
        const wait = Number(res.headers.get("retry-after")) * 1000 || 1000 * 2 ** attempt;
        await this.sleep(wait);
        continue;
      }
      if (!res.ok) {
        const hint = res.status === 401 ? " (provjeri CLINIKO_API_KEY)" : "";
        throw new ClinikoError(`Cliniko HTTP ${res.status}${hint}`, res.status);
      }
      return res.json();
    }
    throw new ClinikoError("Cliniko: iscrpljeni pokušaji", null);
  }

  // Svi termini koji počinju u [from, to). Otkazani se filtriraju kasnije.
  async listAppointments(from, to) {
    const q = new URLSearchParams();
    q.append("q[]", `starts_at:>=${from.toISOString()}`);
    q.append("q[]", `starts_at:<${to.toISOString()}`);
    q.append("per_page", "100");
    q.append("sort", "starts_at");
    let url = `/individual_appointments?${q}`;
    const out = [];
    while (url) {
      const data = await this.get(url);
      for (const a of data.individual_appointments || []) out.push(toAppointment(a));
      url = data.links?.next || null;
    }
    return out;
  }

  // null ako je termin obrisan.
  async getAppointment(id) {
    const data = await this.get(`/individual_appointments/${encodeURIComponent(id)}`, { allow404: true });
    return data ? toAppointment(data) : null;
  }

  async getPatient(id) {
    const p = await this.get(`/patients/${encodeURIComponent(id)}`, { allow404: true });
    if (!p) return null;
    return {
      id: String(p.id),
      firstName: p.preferred_first_name || p.first_name || "",
      lastName: p.last_name || "",
      phones: (p.patient_phone_numbers || []).map((n) => ({ type: n.phone_type || "", number: n.number || "" })),
    };
  }

  // Za provjeru ključa (npm run alat -- provjera).
  getUser() {
    return this.get("/user");
  }
}

module.exports = { ClinikoClient, ClinikoError, baseUrlForKey };
