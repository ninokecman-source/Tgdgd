"""
Tanki FHIR klijent za CEZIH: mTLS s certifikatom klinike, po potrebi OAuth2
token, ponavljanje kod privremenih grešaka i čitljive poruke iz OperationOutcome.
"""

import time

import requests

from .config import CezihConfig


class CezihGreska(Exception):
    def __init__(self, poruka, status=None, ishod=None):
        super().__init__(poruka)
        self.status = status
        self.ishod = ishod


def _iz_ishoda(ishod) -> str:
    """Sažmi FHIR OperationOutcome u jednu čitljivu rečenicu."""
    if not isinstance(ishod, dict) or ishod.get("resourceType") != "OperationOutcome":
        return ""
    dijelovi = []
    for i in ishod.get("issue", []):
        tekst = (i.get("details") or {}).get("text") or i.get("diagnostics") or i.get("code", "")
        dijelovi.append(f"[{i.get('severity', '?')}] {tekst}")
    return "; ".join(dijelovi)


class CezihKlijent:
    def __init__(self, cfg: CezihConfig, session=None):
        self.cfg = cfg
        self.s = session or requests.Session()
        self.s.cert = (cfg.client_cert, cfg.client_key)
        self.s.verify = cfg.ca_bundle or True
        self._token = None
        self._token_do = 0.0

    def _zaglavlja(self) -> dict:
        h = {"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"}
        if self.cfg.token_url:
            h["Authorization"] = f"Bearer {self._dohvati_token()}"
        return h

    def _dohvati_token(self) -> str:
        if self._token and time.time() < self._token_do - 30:
            return self._token
        podaci = {"grant_type": "client_credentials"}
        if self.cfg.scope:
            podaci["scope"] = self.cfg.scope
        r = self.s.post(self.cfg.token_url, data=podaci, timeout=self.cfg.timeout,
                        auth=(self.cfg.client_id, self.cfg.client_secret))
        if r.status_code != 200:
            raise CezihGreska(f"Token nije dobiven (HTTP {r.status_code}).", r.status_code)
        j = r.json()
        self._token = j["access_token"]
        self._token_do = time.time() + int(j.get("expires_in", 300))
        return self._token

    def zahtjev(self, metoda, put, **kw):
        url = f"{self.cfg.base_url}/{put.lstrip('/')}"
        zadnja = None
        for pokusaj in range(self.cfg.retries):
            try:
                r = self.s.request(metoda, url, headers=self._zaglavlja(),
                                   timeout=self.cfg.timeout, **kw)
            except requests.RequestException as e:
                zadnja = CezihGreska(f"Veza s CEZIH-om nije uspjela: {e}")
            else:
                if r.status_code < 400:
                    return r.json() if r.content else {}
                try:
                    ishod = r.json()
                except ValueError:
                    ishod = None
                opis = _iz_ishoda(ishod) or r.text[:200]
                zadnja = CezihGreska(f"CEZIH je odgovorio HTTP {r.status_code}: {opis}",
                                     r.status_code, ishod)
                # 4xx (osim 429) je naša greška - ponavljanje ne pomaže, a nalaz bi mogao stići dvaput.
                if r.status_code < 500 and r.status_code != 429:
                    raise zadnja
            if pokusaj < self.cfg.retries - 1:
                time.sleep(2 ** pokusaj)
        raise zadnja

    def get(self, put, params=None):
        return self.zahtjev("GET", put, params=params)

    def post(self, put, tijelo):
        return self.zahtjev("POST", put, json=tijelo)
