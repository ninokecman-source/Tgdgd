"""SQLAlchemy models for the internal Cliniko + Solo database.

Column choices follow docs/DATA_MODEL.md — see that file for why each
field was picked (or deliberately left out) and where the real API field
names came from.
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AppointmentState(str, enum.Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    UNKNOWN = "UNKNOWN"


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    business_name: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    time_zone_identifier: Mapped[str | None] = mapped_column(String)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class Practitioner(Base):
    __tablename__ = "practitioners"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String)
    active: Mapped[bool | None] = mapped_column(Boolean)

    @property
    def full_name(self) -> str:
        return self.display_name or " ".join(
            p for p in (self.first_name, self.last_name) if p
        )


class AppointmentType(Base):
    __tablename__ = "appointment_types"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    duration_in_minutes: Mapped[int | None] = mapped_column(Integer)
    deposit_price: Mapped[float | None] = mapped_column(Float)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    label: Mapped[str | None] = mapped_column(String)

    @property
    def full_name(self) -> str:
        return self.label or " ".join(
            p for p in (self.first_name, self.last_name) if p
        )


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    business_id: Mapped[str | None] = mapped_column(ForeignKey("businesses.id"))
    practitioner_id: Mapped[str | None] = mapped_column(ForeignKey("practitioners.id"))
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"))
    appointment_type_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointment_types.id")
    )

    starts_at: Mapped[dt.datetime] = mapped_column(DateTime)
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    patient_arrived: Mapped[bool | None] = mapped_column(Boolean)
    did_not_arrive: Mapped[bool | None] = mapped_column(Boolean)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    cancellation_reason_description: Mapped[str | None] = mapped_column(String)
    invoice_status: Mapped[int | None] = mapped_column(Integer)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime)

    appointment_state: Mapped[str] = mapped_column(
        Enum(AppointmentState), default=AppointmentState.UNKNOWN
    )

    business: Mapped[Business | None] = relationship()
    practitioner: Mapped[Practitioner | None] = relationship()
    patient: Mapped[Patient | None] = relationship()
    appointment_type: Mapped[AppointmentType | None] = relationship()


class DailyAvailability(Base):
    __tablename__ = "daily_availabilities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    business_id: Mapped[str | None] = mapped_column(ForeignKey("businesses.id"))
    practitioner_id: Mapped[str | None] = mapped_column(ForeignKey("practitioners.id"))
    day_of_week: Mapped[int] = mapped_column(Integer)
    # Serialized list of {"starts_at": "HH:MM", "ends_at": "HH:MM"} blocks.
    blocks_json: Mapped[str] = mapped_column(Text)


class SoloInvoice(Base):
    __tablename__ = "solo_invoices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    broj_racuna: Mapped[str | None] = mapped_column(String)
    napomene: Mapped[str | None] = mapped_column(Text)
    kupac_naziv: Mapped[str | None] = mapped_column(String)
    kupac_oib: Mapped[str | None] = mapped_column(String)
    datum_racuna: Mapped[dt.date | None] = mapped_column(DateTime)
    datum_isporuke: Mapped[dt.date | None] = mapped_column(DateTime)
    datum_uplate: Mapped[dt.date | None] = mapped_column(DateTime)
    neto_suma: Mapped[float | None] = mapped_column(Float)
    bruto_suma: Mapped[float | None] = mapped_column(Float)
    nacin_placanja: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    # Field names to be confirmed against a real invoice response (see
    # docs/DATA_MODEL.md §2.1) — kept nullable and unused by matching until
    # then.
    jir: Mapped[str | None] = mapped_column(String)
    zki: Mapped[str | None] = mapped_column(String)

    items: Mapped[list["SoloInvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class SoloInvoiceItem(Base):
    __tablename__ = "solo_invoice_items"

    # Solo's `usluge[]` array has no stable id of its own in the API
    # response, so the surrogate key is "{invoice_id}:{index}".
    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("solo_invoices.id"))
    opis_usluge: Mapped[str | None] = mapped_column(String)
    cijena: Mapped[float | None] = mapped_column(Float)
    kolicina: Mapped[float | None] = mapped_column(Float)
    porez_stopa: Mapped[float | None] = mapped_column(Float)
    suma: Mapped[float | None] = mapped_column(Float)

    invoice: Mapped[SoloInvoice] = relationship(back_populates="items")


class AppointmentInvoiceLink(Base):
    __tablename__ = "appointment_invoice_links"

    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.id"), primary_key=True
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("solo_invoices.id"), primary_key=True
    )
    confidence_score: Mapped[float] = mapped_column(Float)
    match_method: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow
    )
