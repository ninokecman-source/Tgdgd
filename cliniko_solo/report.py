"""Prints KPIs for a period, per-clinic and per-practitioner. Run after
`sync.py`. This is the last step before the numbers go to Claude (or any
dashboard) — Claude gets exactly this dict, never raw rows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from sqlalchemy import select

from .db import make_session
from .kpi_engine import compute_kpis
from .models import Practitioner


def print_kpis(label: str, kpis: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"Dostupno: {kpis['available_hours']} h")
    print(f"Odrađeno: {kpis['completed_hours']} h")
    print(f"Otkazano: {kpis['cancelled_hours']} h | No-show: {kpis['no_show_hours']} h")
    print(f"Slobodno: {kpis['free_hours']} h")
    if kpis["utilization"] is not None:
        print(f"Iskorištenost: {kpis['utilization'] * 100:.1f}%")
    print(f"Prihod: {kpis['revenue']} EUR")
    if kpis["revenue_per_available_hour"] is not None:
        print(f"Prihod / dostupni sat: {kpis['revenue_per_available_hour']} EUR")
    if kpis["unbilled_completed_appointments"]:
        print(
            f"Odrađeni termini bez potvrđenog računa: "
            f"{kpis['unbilled_completed_appointments']} (provjeriti ručno)"
        )
    if kpis["lost_revenue_estimate"] is not None:
        print(f"Procjena izgubljenog prihoda: {kpis['lost_revenue_estimate']} EUR")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print KPIs for a period")
    parser.add_argument("--config", default="cliniko_solo/config.json")
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--json", action="store_true", help="Ispiši sirovi JSON umjesto formatiranog teksta"
    )
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)

    session = make_session(config["db_url"])
    date_from = dt.date.fromisoformat(args.date_from)
    date_to = dt.date.fromisoformat(args.date_to)
    auto_accept = config.get("matching", {}).get("auto_accept_confidence", 0.7)

    clinic_kpis = compute_kpis(session, date_from, date_to, auto_accept_confidence=auto_accept)
    per_practitioner = []
    for practitioner in session.scalars(select(Practitioner).where(Practitioner.active.is_(True))):
        kpis = compute_kpis(
            session, date_from, date_to, practitioner.id, auto_accept_confidence=auto_accept
        )
        kpis["practitioner_name"] = practitioner.full_name
        per_practitioner.append(kpis)

    if args.json:
        print(json.dumps({"clinic": clinic_kpis, "practitioners": per_practitioner}, indent=2))
        return

    print_kpis("KLINIKA", clinic_kpis)
    for kpis in per_practitioner:
        print_kpis(kpis["practitioner_name"], kpis)


if __name__ == "__main__":
    main()
