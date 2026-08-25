"""Orchestrator: Cliniko API + Solo API -> local DB -> matching.

This is the "DATA ENGINE" box from the architecture: nothing here talks to
Claude or renders a report. Run `python -m cliniko_solo.sync` to pull the
latest data; then use `report.py` to compute and print KPIs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from .cliniko_client import ClinikoClient
from .db import make_session
from .matching import run_matching
from .models import (
    Appointment,
    AppointmentState,
    AppointmentType,
    Business,
    DailyAvailability,
    Patient,
    Practitioner,
    SoloInvoice,
    SoloInvoiceItem,
)
from .solo_client import SoloClient


def _parse_dt(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _parse_date(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def _linked_id(link: dict | None) -> str | None:
    """Cliniko relationship fields look like {"links": {"self": ".../123"}}."""
    if not link:
        return None
    self_link = link.get("links", {}).get("self", "")
    return self_link.rstrip("/").rsplit("/", 1)[-1] or None


def _appointment_state(raw: dict) -> AppointmentState:
    if raw.get("cancelled_at"):
        return AppointmentState.CANCELLED
    if raw.get("did_not_arrive"):
        return AppointmentState.NO_SHOW
    if raw.get("patient_arrived"):
        return AppointmentState.COMPLETED
    starts_at = _parse_dt(raw["starts_at"])
    if starts_at and starts_at > dt.datetime.now(starts_at.tzinfo):
        return AppointmentState.BOOKED
    return AppointmentState.UNKNOWN


def sync_cliniko(session, client: ClinikoClient, since: dt.date, until: dt.date) -> None:
    for raw in client.get_businesses():
        session.merge(
            Business(
                id=raw["id"],
                business_name=raw.get("business_name"),
                city=raw.get("city"),
                time_zone_identifier=raw.get("time_zone_identifier"),
                archived_at=_parse_dt(raw.get("archived_at")),
            )
        )

    for raw in client.get_practitioners():
        session.merge(
            Practitioner(
                id=raw["id"],
                first_name=raw.get("first_name"),
                last_name=raw.get("last_name"),
                display_name=raw.get("display_name"),
                active=raw.get("active"),
            )
        )

    for raw in client.get_appointment_types():
        session.merge(
            AppointmentType(
                id=raw["id"],
                name=raw.get("name"),
                category=raw.get("category"),
                duration_in_minutes=raw.get("duration_in_minutes"),
                deposit_price=float(raw["deposit_price"]) if raw.get("deposit_price") else None,
            )
        )

    for raw in client.get_patients():
        session.merge(
            Patient(
                id=raw["id"],
                first_name=raw.get("first_name"),
                last_name=raw.get("last_name"),
                label=raw.get("label"),
            )
        )

    for raw in client.get_daily_availabilities():
        session.merge(
            DailyAvailability(
                id=raw["id"],
                business_id=_linked_id(raw.get("business")),
                practitioner_id=_linked_id(raw.get("practitioner")),
                day_of_week=raw["day_of_week"],
                blocks_json=json.dumps(raw.get("availabilities") or []),
            )
        )

    starts_after = dt.datetime.combine(since, dt.time.min).isoformat() + "Z"
    starts_before = dt.datetime.combine(until, dt.time.max).isoformat() + "Z"
    for raw in client.get_appointments(starts_after, starts_before):
        if raw.get("deleted_at"):
            continue
        session.merge(
            Appointment(
                id=raw["id"],
                business_id=_linked_id(raw.get("business")),
                practitioner_id=_linked_id(raw.get("practitioner")),
                patient_id=_linked_id(raw.get("patient")),
                appointment_type_id=_linked_id(raw.get("appointment_type")),
                starts_at=_parse_dt(raw["starts_at"]),
                ends_at=_parse_dt(raw.get("ends_at")),
                patient_arrived=raw.get("patient_arrived"),
                did_not_arrive=raw.get("did_not_arrive"),
                cancelled_at=_parse_dt(raw.get("cancelled_at")),
                cancellation_reason_description=raw.get("cancellation_reason_description"),
                invoice_status=raw.get("invoice_status"),
                archived_at=_parse_dt(raw.get("archived_at")),
                deleted_at=None,
                appointment_state=_appointment_state(raw),
            )
        )
    session.commit()


def sync_solo(session, client: SoloClient) -> None:
    for raw in client.list_invoices():
        invoice_id = str(raw["id"])
        session.merge(
            SoloInvoice(
                id=invoice_id,
                broj_racuna=raw.get("broj_racuna"),
                napomene=raw.get("napomene"),
                kupac_naziv=raw.get("kupac_naziv"),
                kupac_oib=raw.get("kupac_oib"),
                datum_racuna=_parse_date(raw.get("datum_racuna")),
                datum_isporuke=_parse_date(raw.get("datum_isporuke")),
                datum_uplate=_parse_date(raw.get("datum_uplate")),
                neto_suma=_to_float(raw.get("neto_suma")),
                bruto_suma=_to_float(raw.get("bruto_suma")),
                nacin_placanja=raw.get("nacin_placanja"),
                status=str(raw.get("status")) if raw.get("status") is not None else None,
                jir=raw.get("jir"),
                zki=raw.get("zki"),
            )
        )
        for i, item in enumerate(raw.get("usluge") or []):
            session.merge(
                SoloInvoiceItem(
                    id=f"{invoice_id}:{i}",
                    invoice_id=invoice_id,
                    opis_usluge=item.get("opis_usluge"),
                    cijena=_to_float(item.get("cijena")),
                    kolicina=_to_float(item.get("kolicina")),
                    porez_stopa=_to_float(item.get("porez_stopa")),
                    suma=_to_float(item.get("suma")),
                )
            )
    session.commit()


def _to_float(value) -> float | None:
    if value is None:
        return None
    # Solo formats decimals with a comma (e.g. "24,99") in its docs example.
    return float(str(value).replace(",", "."))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Cliniko + Solo into the local DB")
    parser.add_argument("--config", default="cliniko_solo/config.json")
    parser.add_argument("--since", help="YYYY-MM-DD, default: 90 days ago")
    parser.add_argument("--until", help="YYYY-MM-DD, default: today")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)

    today = dt.date.today()
    since = dt.date.fromisoformat(args.since) if args.since else today - dt.timedelta(days=90)
    until = dt.date.fromisoformat(args.until) if args.until else today

    session = make_session(config["db_url"])

    cliniko = ClinikoClient(
        api_key=config["cliniko_api_key"],
        shard=config["cliniko_shard"],
        user_agent=config["cliniko_user_agent"],
    )
    print(f"Dohvaćam Cliniko podatke ({since} - {until})...")
    sync_cliniko(session, cliniko, since, until)

    solo = SoloClient(token=config["solo_api_token"])
    print("Dohvaćam Solo račune...")
    sync_solo(session, solo)

    print("Povezujem termine s računima...")
    summary = run_matching(session, config.get("matching", {}))
    print(
        f"Gotovo: {summary['linked']} povezano, "
        f"{summary['manual_review']} za ručnu provjeru, "
        f"{summary['unmatched_invoices']} računa bez para."
    )


if __name__ == "__main__":
    main()
