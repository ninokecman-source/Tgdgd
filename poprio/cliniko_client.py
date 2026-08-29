"""Tanki klijent za Cliniko API (v1) - samo ono što nam treba za sinkronizaciju plaćenih računa."""

import requests

STATUS_PAID = 20


class ClinikoClient:
    def __init__(self, api_key, user_agent, shard=None):
        self.api_key = api_key
        self.shard = shard or api_key.rsplit("-", 1)[-1]
        self.base_url = f"https://api.{self.shard}.cliniko.com/v1"
        self.session = requests.Session()
        self.session.auth = (api_key, "")
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": user_agent,
        })

    def _get(self, path, params=None):
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_paid_invoices(self, updated_since=None, per_page=100):
        """Vraća sve račune sa statusom Paid (20), opcionalno samo one ažurirane nakon `updated_since` (ISO 8601 UTC)."""
        filters = [f"status:={STATUS_PAID}"]
        if updated_since:
            filters.append(f"updated_at:>{updated_since}")

        invoices = []
        page = 1
        while True:
            data = self._get("/invoices", params={
                "q[]": filters,
                "page": page,
                "per_page": per_page,
            })
            invoices.extend(data.get("invoices", []))
            next_link = data.get("links", {}).get("next")
            if not next_link:
                break
            page += 1
        return invoices

    def get_patient(self, patient_id):
        return self._get(f"/patients/{patient_id}")
