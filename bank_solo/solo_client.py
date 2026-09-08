"""Tanki klijent za Solo API - izrada ponude (quote, nefiskalizirano)."""

import time

import requests

BASE_URL = "https://api.solo.com.hr"
MIN_SECONDS_BETWEEN_REQUESTS = 6  # Solo traži barem 5s - malo marže


class SoloAPIError(Exception):
    def __init__(self, status, message, payload=None):
        super().__init__(f"Solo API greška {status}: {message}")
        self.status = status
        self.message = message
        self.payload = payload


class SoloClient:
    def __init__(self, api_token):
        self.api_token = api_token
        self.session = requests.Session()
        self._last_request_time = None

    def create_ponuda(self, tip_kupca, tip_usluge, nacin_placanja, kupac_naziv,
                       stavke, kupac_oib=None, kupac_adresa=None, napomene=None):
        """
        stavke: lista dictova {"opis": str, "cijena": float, "kolicina": float, "porez_stopa": int}
        Vraća parsirani 'ponuda' dio odgovora (id, broj_ponude, pdf, ...).
        """
        payload = [
            ("token", self.api_token),
            ("tip_kupca", tip_kupca),
            ("tip_usluge", tip_usluge),
            ("nacin_placanja", nacin_placanja),
            ("kupac_naziv", kupac_naziv),
        ]
        if kupac_adresa:
            payload.append(("kupac_adresa", kupac_adresa))
        if kupac_oib:
            payload.append(("kupac_oib", kupac_oib))
        if napomene:
            payload.append(("napomene", napomene))

        for i, stavka in enumerate(stavke, start=1):
            payload.append(("usluga", i))
            payload.append((f"opis_usluge_{i}", stavka["opis"]))
            payload.append((f"cijena_{i}", f"{stavka['cijena']:.2f}".replace(".", ",")))
            payload.append((f"popust_{i}", "0,00"))
            payload.append((f"kolicina_{i}", stavka.get("kolicina", 1)))
            payload.append((f"porez_stopa_{i}", stavka["porez_stopa"]))

        return self._post("ponuda", payload, result_key="ponuda")

    def _wait_for_rate_limit(self):
        if self._last_request_time is None:
            return
        elapsed = time.monotonic() - self._last_request_time
        remaining = MIN_SECONDS_BETWEEN_REQUESTS - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _post(self, endpoint, payload, result_key="racun"):
        self._wait_for_rate_limit()
        self._last_request_time = time.monotonic()
        resp = self.session.post(f"{BASE_URL}/{endpoint}", data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != 0:
            raise SoloAPIError(data.get("status"), data.get("message"), payload)

        return data[result_key]
