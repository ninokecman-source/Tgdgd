"""Deterministic KPI calculations over the local DB — see
docs/DATA_MODEL.md §5 for the formulas. Claude (or any other consumer)
receives only the output of `compute_kpis`, never raw appointment/invoice
rows, per the "Claude ne bi trebao računati osnovne KPI-jeve" principle
from the original architecture discussion.
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Appointment,
    AppointmentInvoiceLink,
    AppointmentState,
    DailyAvailability,
    SoloInvoice,
)


def _hours(minutes: float) -> float:
    return round(minutes / 60, 2)


def _available_hours(
    session: Session, date_from: dt.date, date_to: dt.date, practitioner_id: str | None
) -> float:
    """Sums weekly recurring `daily_availabilities` blocks across every day
    in [date_from, date_to]. Does NOT yet subtract one-off Unavailable
    Blocks (holidays, sick leave) — see docs/DATA_MODEL.md §1.6. Treat the
    result as an upper bound on real availability until that's added."""
    query = select(DailyAvailability)
    if practitioner_id:
        query = query.where(DailyAvailability.practitioner_id == practitioner_id)
    availabilities = session.scalars(query).all()

    minutes_by_weekday: dict[int, float] = {}
    for avail in availabilities:
        blocks = json.loads(avail.blocks_json)
        total_minutes = 0.0
        for block in blocks:
            start_h, start_m = map(int, block["starts_at"].split(":"))
            end_h, end_m = map(int, block["ends_at"].split(":"))
            total_minutes += (end_h * 60 + end_m) - (start_h * 60 + start_m)
        minutes_by_weekday[avail.day_of_week] = (
            minutes_by_weekday.get(avail.day_of_week, 0) + total_minutes
        )

    total = 0.0
    day = date_from
    while day <= date_to:
        # Cliniko day_of_week: 0=Monday ... 6=Sunday, matches date.weekday().
        total += minutes_by_weekday.get(day.weekday(), 0)
        day += dt.timedelta(days=1)
    return _hours(total)


def _appointment_minutes(appointment: Appointment) -> float:
    if appointment.appointment_type and appointment.appointment_type.duration_in_minutes:
        return appointment.appointment_type.duration_in_minutes
    if appointment.ends_at:
        return (appointment.ends_at - appointment.starts_at).total_seconds() / 60
    return 0.0


def compute_kpis(
    session: Session,
    date_from: dt.date,
    date_to: dt.date,
    practitioner_id: str | None = None,
    auto_accept_confidence: float = 0.7,
) -> dict:
    query = select(Appointment).where(
        Appointment.starts_at >= dt.datetime.combine(date_from, dt.time.min),
        Appointment.starts_at <= dt.datetime.combine(date_to, dt.time.max),
        Appointment.deleted_at.is_(None),
    )
    if practitioner_id:
        query = query.where(Appointment.practitioner_id == practitioner_id)
    appointments = session.scalars(query).all()

    booked_minutes = completed_minutes = cancelled_minutes = no_show_minutes = 0.0
    completed_appointment_ids: list[str] = []

    for appt in appointments:
        minutes = _appointment_minutes(appt)
        if appt.appointment_state == AppointmentState.CANCELLED:
            cancelled_minutes += minutes
            continue
        booked_minutes += minutes
        if appt.appointment_state == AppointmentState.COMPLETED:
            completed_minutes += minutes
            completed_appointment_ids.append(appt.id)
        elif appt.appointment_state == AppointmentState.NO_SHOW:
            no_show_minutes += minutes

    available_hours = _available_hours(session, date_from, date_to, practitioner_id)
    booked_hours = _hours(booked_minutes)
    completed_hours = _hours(completed_minutes)
    cancelled_hours = _hours(cancelled_minutes)
    no_show_hours = _hours(no_show_minutes)
    free_hours = max(0.0, round(available_hours - booked_hours, 2))

    revenue = 0.0
    unbilled_completed = 0
    if completed_appointment_ids:
        links = session.scalars(
            select(AppointmentInvoiceLink).where(
                AppointmentInvoiceLink.appointment_id.in_(completed_appointment_ids),
                AppointmentInvoiceLink.confidence_score >= auto_accept_confidence,
            )
        ).all()
        invoice_ids = {link.invoice_id for link in links}
        billed_appointment_ids = {link.appointment_id for link in links}
        if invoice_ids:
            invoices = session.scalars(
                select(SoloInvoice).where(SoloInvoice.id.in_(invoice_ids))
            ).all()
            revenue = sum(inv.bruto_suma or 0 for inv in invoices)
        unbilled_completed = len(
            set(completed_appointment_ids) - billed_appointment_ids
        )

    utilization = round(completed_hours / available_hours, 4) if available_hours else None
    revenue_per_available_hour = (
        round(revenue / available_hours, 2) if available_hours else None
    )
    revenue_per_completed_hour = (
        round(revenue / completed_hours, 2) if completed_hours else None
    )
    lost_revenue_estimate = (
        round(free_hours * revenue_per_completed_hour, 2)
        if revenue_per_completed_hour
        else None
    )

    return {
        "period": {"from": str(date_from), "to": str(date_to)},
        "practitioner_id": practitioner_id,
        "available_hours": available_hours,
        "booked_hours": booked_hours,
        "completed_hours": completed_hours,
        "cancelled_hours": cancelled_hours,
        "no_show_hours": no_show_hours,
        "free_hours": free_hours,
        "utilization": utilization,
        "revenue": round(revenue, 2),
        "revenue_per_available_hour": revenue_per_available_hour,
        "revenue_per_completed_hour": revenue_per_completed_hour,
        "unbilled_completed_appointments": unbilled_completed,
        "lost_capacity_breakdown": {
            "free_hours": free_hours,
            "cancelled_hours": cancelled_hours,
            "no_show_hours": no_show_hours,
        },
        "lost_revenue_estimate": lost_revenue_estimate,
    }
