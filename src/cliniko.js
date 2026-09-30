const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class ClinikoError extends Error {
  constructor(status, body) {
    super(`Cliniko API ${status}: ${String(body).slice(0, 300)}`);
    this.status = status;
  }
}

/**
 * Minimalni Cliniko API klijent.
 * Dokumentacija: https://docs.api.cliniko.com/
 *  - Basic auth: API ključ kao korisničko ime, prazna lozinka
 *  - Shard (au1, uk1, ...) je na kraju API ključa
 *  - User-Agent mora sadržavati naziv i kontakt e-mail
 *  - Limit: 200 zahtjeva / min -> 429 + X-RateLimit-Reset
 */
export class ClinikoClient {
  constructor({ apiKey, userAgent, baseUrl }) {
    const shard = apiKey.includes('-') ? apiKey.split('-').pop() : 'au1';
    this.baseUrl = (baseUrl || `https://api.${shard}.cliniko.com/v1`).replace(/\/$/, '');
    this.auth = 'Basic ' + Buffer.from(apiKey + ':').toString('base64');
    this.userAgent = userAgent;
    this.patientCache = new Map();
  }

  async request(pathOrUrl, { method = 'GET', body } = {}) {
    const url = pathOrUrl.startsWith('http') ? pathOrUrl : this.baseUrl + pathOrUrl;
    for (let attempt = 0; ; attempt++) {
      const res = await fetch(url, {
        method,
        headers: {
          Authorization: this.auth,
          'User-Agent': this.userAgent,
          Accept: 'application/json',
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(30_000), // bez toga zapeli zahtjev zauvijek blokira slanje
      });
      if (res.status === 429 && attempt < 5) {
        const reset = Number(res.headers.get('x-ratelimit-reset'));
        const wait = reset ? Math.max(1000, reset * 1000 - Date.now()) : 2000 * 2 ** attempt;
        await sleep(Math.min(wait, 65_000));
        continue;
      }
      if (res.status >= 500 && attempt < 3) {
        await sleep(1000 * 2 ** attempt);
        continue;
      }
      if (!res.ok) throw new ClinikoError(res.status, await res.text());
      if (res.status === 204) return null;
      return res.json();
    }
  }

  async *paginate(path, key) {
    let url = path;
    while (url) {
      const data = await this.request(url);
      for (const item of data?.[key] || []) yield item;
      url = data?.links?.next || null;
    }
  }

  static rangeQuery(fromUtc, toUtc) {
    const p = new URLSearchParams();
    p.append('q[]', `starts_at:>=${fromUtc}`);
    p.append('q[]', `starts_at:<${toUtc}`);
    p.append('per_page', '100');
    return p.toString();
  }

  individualAppointments(fromUtc, toUtc) {
    return this.paginate(`/individual_appointments?${ClinikoClient.rangeQuery(fromUtc, toUtc)}`, 'individual_appointments');
  }

  groupAppointments(fromUtc, toUtc) {
    return this.paginate(`/group_appointments?${ClinikoClient.rangeQuery(fromUtc, toUtc)}`, 'group_appointments');
  }

  attendees(groupAppointmentId) {
    return this.paginate(`/group_appointments/${groupAppointmentId}/attendees?per_page=100`, 'attendees');
  }

  async patientByLink(link) {
    if (!this.patientCache.has(link)) this.patientCache.set(link, await this.request(link));
    return this.patientCache.get(link);
  }

  getIndividualAppointment(id) {
    return this.request(`/individual_appointments/${id}`);
  }

  updateIndividualAppointment(id, fields) {
    return this.request(`/individual_appointments/${id}`, { method: 'PATCH', body: fields });
  }

  currentUser() {
    return this.request('/user');
  }
}

/** ID iz Cliniko poveznice, npr. .../patients/12345 -> "12345" */
export const idFromLink = (link) => String(link || '').split('/').filter(Boolean).pop() || null;
