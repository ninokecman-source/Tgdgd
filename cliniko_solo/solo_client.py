"""Thin client for the Solo (solo.com.hr) invoicing API.

See docs/DATA_MODEL.md §2 for field details. Auth is a `token` query
parameter (not a header), per solo.com.hr/api-dokumentacija. Only the GET
(read) endpoint is used for analytics; `create_invoice` exists only to
support the "write the Cliniko appointment ID into `napomene`" matching
shortcut described in §3, and is not part of the sync/report flow.
"""
from __future__ import annotations

from typing import Any, Iterator

import requests

BASE_URL = "https://api.solo.com.hr"

# Status codes Solo documents for /racun (see docs/DATA_MODEL.md §2.1).
STATUS_INVALID_TOKEN = 101
STATUS_INVOICE_NOT_FOUND = 122
STATUS_NO_INVOICES = 123


class SoloClient:
    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        params = dict(params or {})
        params["token"] = self.token
        resp = self.session.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_invoice(self, invoice_id: str) -> dict | None:
        data = self._get("/racun", {"id": invoice_id})
        if data.get("status") in (STATUS_INVOICE_NOT_FOUND, STATUS_NO_INVOICES):
            return None
        return data.get("racun")

    def list_invoices(self) -> Iterator[dict]:
        page = 1
        while True:
            data = self._get("/racun", {"stranica": page})
            if data.get("status") == STATUS_NO_INVOICES:
                return
            racuni = data.get("racun")
            if not racuni:
                return
            # A single-invoice response returns `racun` as one object;
            # a listing returns a list — normalize both.
            yield from (racuni if isinstance(racuni, list) else [racuni])
            if not isinstance(racuni, list) or len(racuni) < 1000:
                return
            page += 1

    def create_invoice(self, **fields: Any) -> dict:
        """`fields` follow docs/DATA_MODEL.md §2.2 verbatim (tip_usluge,
        tip_racuna, tip_kupca, nacin_placanja, opis_usluge_1, cijena_1, ...).
        `fiskalizacija` is intentionally not a parameter here — Solo has
        handled fiscalization itself since December 2025."""
        params = dict(fields)
        params["token"] = self.token
        resp = self.session.post(f"{BASE_URL}/racun", data=params)
        resp.raise_for_status()
        return resp.json()
