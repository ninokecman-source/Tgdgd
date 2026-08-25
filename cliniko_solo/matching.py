"""Cross-system matching: link Cliniko appointments to Solo invoices.

Implements the rules from docs/DATA_MODEL.md §3, in order — the first rule
that finds a candidate wins. Nothing here mutates Cliniko or Solo; it only
writes rows into `appointment_invoice_links` in the local DB.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Appointment, AppointmentInvoiceLink, AppointmentState, SoloInvoice

REFERENCE_PATTERN = re.compile(r"CLINIKO[-:]?(\d+)", re.IGNORECASE)


def _reference_matches(invoice: SoloInvoice) -> str | None:
    if not invoice.napomene:
        return None
    match = REFERENCE_PATTERN.search(invoice.napomene)
    return match.group(1) if match else None


def _amount_within_tolerance(
    invoice_amount: float, reference_amount: float, pct: float, absolute: float
) -> bool:
    tolerance = max(reference_amount * pct / 100, absolute)
    return abs(invoice_amount - reference_amount) <= tolerance


def _name_matches(invoice_name: str | None, patient_name: str | None, threshold: int) -> bool:
    if not invoice_name or not patient_name:
        return False
    return fuzz.token_sort_ratio(invoice_name, patient_name) >= threshold


def run_matching(session: Session, matching_config: dict) -> dict:
    """Returns a summary dict: {linked, manual_review, unmatched_invoices}."""
    pct = matching_config.get("amount_tolerance_percent", 10)
    absolute = matching_config.get("amount_tolerance_absolute", 5)
    name_threshold = matching_config.get("name_match_threshold", 80)

    already_linked_appointment_ids = {
        row.appointment_id for row in session.scalars(select(AppointmentInvoiceLink))
    }
    already_linked_invoice_ids = {
        row.invoice_id for row in session.scalars(select(AppointmentInvoiceLink))
    }

    completed = session.scalars(
        select(Appointment).where(
            Appointment.appointment_state == AppointmentState.COMPLETED,
            Appointment.id.notin_(already_linked_appointment_ids or [""]),
        )
    ).all()
    invoices = session.scalars(
        select(SoloInvoice).where(
            SoloInvoice.id.notin_(already_linked_invoice_ids or [""])
        )
    ).all()

    invoices_by_id = {inv.id: inv for inv in invoices}
    linked = 0
    manual_review = 0

    # Rule 1: exact reference in `napomene`.
    for invoice in list(invoices_by_id.values()):
        appointment_id = _reference_matches(invoice)
        if appointment_id and any(a.id == appointment_id for a in completed):
            session.add(
                AppointmentInvoiceLink(
                    appointment_id=appointment_id,
                    invoice_id=invoice.id,
                    confidence_score=1.0,
                    match_method="exact_reference",
                )
            )
            linked += 1
            del invoices_by_id[invoice.id]
            completed = [a for a in completed if a.id != appointment_id]

    # Rule 2/3: date + amount + fuzzy patient name.
    for appointment in completed:
        if not appointment.appointment_type or appointment.appointment_type.deposit_price is None:
            continue
        appt_date = appointment.starts_at.date()
        reference_price = appointment.appointment_type.deposit_price
        patient_name = appointment.patient.full_name if appointment.patient else None

        candidates = []
        for invoice in invoices_by_id.values():
            invoice_date = invoice.datum_isporuke or invoice.datum_racuna
            if not invoice_date or invoice_date.date() != appt_date:
                continue
            if invoice.bruto_suma is None or not _amount_within_tolerance(
                invoice.bruto_suma, reference_price, pct, absolute
            ):
                continue
            candidates.append(invoice)

        if len(candidates) == 0:
            continue
        if len(candidates) > 1:
            # Ambiguous same-day, same-amount candidates -> manual review,
            # per docs/DATA_MODEL.md §3 rule 3.
            manual_review += 1
            continue

        invoice = candidates[0]
        name_ok = _name_matches(invoice.kupac_naziv, patient_name, name_threshold)
        confidence = 0.85 if name_ok else 0.6
        session.add(
            AppointmentInvoiceLink(
                appointment_id=appointment.id,
                invoice_id=invoice.id,
                confidence_score=confidence,
                match_method="date_amount_name" if name_ok else "date_amount",
            )
        )
        linked += 1
        del invoices_by_id[invoice.id]

    session.commit()
    return {
        "linked": linked,
        "manual_review": manual_review,
        "unmatched_invoices": len(invoices_by_id),
    }
