"""Thin client for the Cliniko REST API.

See docs/DATA_MODEL.md §1 for the exact fields this pulls and why. Auth,
pagination and rate-limit handling follow docs.api.cliniko.com verbatim:
HTTP Basic (API key as username, blank password), a required User-Agent,
`page`/`per_page` pagination via `links.next`, and 429 + `X-RateLimit-Reset`
on rate-limit.
"""
from __future__ import annotations

import time
from typing import Any, Iterator

import requests


class ClinikoClient:
    def __init__(self, api_key: str, shard: str, user_agent: str):
        self.base_url = f"https://api.{shard}.cliniko.com/v1"
        self.session = requests.Session()
        self.session.auth = (api_key, "")
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": user_agent}
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        while True:
            resp = self.session.get(url, params=params)
            if resp.status_code == 429:
                reset_at = int(resp.headers.get("X-RateLimit-Reset", 0))
                time.sleep(max(1, reset_at - int(time.time())))
                continue
            resp.raise_for_status()
            return resp.json()

    def _paginate(
        self, path: str, params: dict[str, Any] | None = None, per_page: int = 100
    ) -> Iterator[dict]:
        params = dict(params or {})
        params["per_page"] = per_page
        next_url: str | None = path
        next_params: dict[str, Any] | None = params
        while next_url:
            page = self._get(next_url, next_params)
            key = next(k for k in page if k != "links" and k != "total_entries")
            yield from page[key]
            next_url = page.get("links", {}).get("next")
            next_params = None  # `next` already carries all query params

    def get_businesses(self) -> Iterator[dict]:
        return self._paginate("/businesses")

    def get_practitioners(self) -> Iterator[dict]:
        return self._paginate("/practitioners")

    def get_appointment_types(self) -> Iterator[dict]:
        return self._paginate("/appointment_types")

    def get_patients(self) -> Iterator[dict]:
        return self._paginate("/patients")

    def get_daily_availabilities(self) -> Iterator[dict]:
        return self._paginate("/daily_availabilities")

    def get_appointments(
        self, starts_after: str | None = None, starts_before: str | None = None
    ) -> Iterator[dict]:
        """`starts_after`/`starts_before` are ISO 8601 datetimes (UTC)."""
        q = []
        if starts_after:
            q.append(f"starts_at:>={starts_after}")
        if starts_before:
            q.append(f"starts_at:<={starts_before}")
        params = {"q[]": q} if q else None
        return self._paginate("/individual_appointments", params)

    def get_invoices(self) -> Iterator[dict]:
        """Cliniko's own billing module, if the clinic uses it — see the
        note in docs/DATA_MODEL.md §1.7 before relying on this instead of
        Solo for revenue."""
        return self._paginate("/invoices")
