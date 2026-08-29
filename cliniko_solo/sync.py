"""
Glavna skripta: pronalazi novoplaćene Cliniko račune i fiskalizira ih preko Solo API-ja.

Namijenjena pokretanju preko crona (svake 1-2 minute), isto kao zoho_to_excel.py.
Pamti stanje u SQLite bazi (state_db_path) pa svaki Cliniko račun šalje u Solo
točno jednom, bez obzira koliko se puta skripta pokrene.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cliniko_client import ClinikoClient
from solo_client import SoloClient, SoloAPIError
from state import StateStore
from mailer import send_invoice_pdf

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Nema {CONFIG_PATH}. Kopiraj config.example.json u config.json i popuni podatke."
        )
    return json.loads(CONFIG_PATH.read_text())


def extract_patient_id(invoice):
    self_link = invoice.get("patient", {}).get("links", {}).get("self", "")
    match = re.search(r"/patients/(\d+)", self_link)
    return match.group(1) if match else None


def extract_oib(patient, section_name="Fiskalizacija", field_label="OIB"):
    """Cliniko nema ugrađeno polje za OIB - klinika ga drži kao custom field
    (sekcija "Fiskalizacija", polje "OIB"). Cliniko-ova javna dokumentacija ne
    navodi točan naziv ključeva unutar `fields[]`, pa ova funkcija provjerava
    oba plauzibilna varijantna naziva (`label`/`name` i `response`/`value`).
    Provjeri na jednom stvarnom pacijentu s upisanim OIB-om prije nego se
    osloniš na ovo u produkciji - ako ne vrati ništa, ispiši
    `patient["custom_fields"]` i prilagodi ključeve."""
    sections = (patient.get("custom_fields") or {}).get("sections") or []
    for section in sections:
        if section.get("name") != section_name:
            continue
        for field in section.get("fields") or []:
            label = field.get("label") or field.get("name")
            if label == field_label:
                return field.get("response") or field.get("value") or None
    return None


def format_address(patient):
    """Sastavlja `kupac_adresa` za Solo iz standardnih Cliniko adresnih polja."""
    street = ", ".join(
        p for p in (patient.get("address_1"), patient.get("address_2")) if p
    )
    city_line = " ".join(
        p for p in (patient.get("post_code"), patient.get("city")) if p
    )
    return ", ".join(p for p in (street, city_line) if p) or None


def iso_now(offset_seconds=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def run(backfill_days=None):
    config = load_config()

    cliniko = ClinikoClient(
        api_key=config["cliniko_api_key"],
        user_agent=config["cliniko_user_agent"],
    )
    solo = SoloClient(api_token=config["solo_api_token"])
    state = StateStore(config["state_db_path"])

    watermark = state.get_watermark()
    if not watermark:
        lookback = timedelta(days=backfill_days) if backfill_days else timedelta(minutes=10)
        watermark = (datetime.now(timezone.utc) - lookback).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"Prvo pokretanje, gledam račune ažurirane nakon {watermark}")

    invoices = cliniko.get_paid_invoices(updated_since=watermark)
    print(f"Pronađeno {len(invoices)} plaćenih računa od {watermark}")

    latest_updated_at = watermark
    processed_count = 0

    for invoice in invoices:
        cliniko_id = invoice["id"]
        updated_at = invoice.get("updated_at", latest_updated_at)
        if updated_at > latest_updated_at:
            latest_updated_at = updated_at

        if state.is_processed(cliniko_id):
            continue

        patient_id = extract_patient_id(invoice)
        patient = cliniko.get_patient(patient_id) if patient_id else {}
        patient_name = f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip()
        patient_email = patient.get("email")
        patient_oib = extract_oib(patient)
        patient_address = format_address(patient)

        # Cliniko total_amount je iznos koji je pacijent stvarno platio (bruto,
        # s PDV-om). Solo traži cijenu BEZ PDV-a i sam ga dodaje, pa moramo
        # računati unatrag da bruto_suma u Solo-u ispadne isti iznos.
        gross_amount = float(invoice.get("total_amount"))
        tax_rate = config["solo_default_tax_rate"]
        net_amount = round(gross_amount / (1 + tax_rate / 100), 2)

        stavke = [{
            "opis": config["solo_default_service_description"],
            "cijena": net_amount,
            "kolicina": 1,
            "porez_stopa": tax_rate,
        }]
        document_type = config.get("solo_document_type", "racun")

        try:
            if document_type == "ponuda":
                racun = solo.create_ponuda(
                    tip_kupca=config["solo_tip_kupca"],
                    tip_usluge=config["solo_tip_usluge"],
                    nacin_placanja=config["solo_nacin_placanja"],
                    kupac_naziv=patient_name or "Kupac",
                    kupac_oib=patient_oib,
                    kupac_adresa=patient_address,
                    stavke=stavke,
                )
                broj = racun.get("broj_ponude")
            else:
                racun = solo.create_invoice(
                    tip_racuna=config["solo_tip_racuna"],
                    tip_kupca=config["solo_tip_kupca"],
                    tip_usluge=config["solo_tip_usluge"],
                    nacin_placanja=config["solo_nacin_placanja"],
                    kupac_naziv=patient_name or "Kupac",
                    kupac_oib=patient_oib,
                    kupac_adresa=patient_address,
                    stavke=stavke,
                )
                broj = racun.get("broj_racuna")
        except SoloAPIError as e:
            print(f"[GREŠKA] Cliniko račun {cliniko_id}: {e}", file=sys.stderr)
            continue

        state.mark_processed(cliniko_id, racun)
        processed_count += 1
        print(f"Cliniko #{cliniko_id} -> Solo {document_type} {broj} (JIR {racun.get('jir', '-')})")

        if config.get("send_pdf_email") and patient_email and racun.get("pdf"):
            try:
                send_invoice_pdf(config, patient_email, patient_name, racun["pdf"], broj)
            except Exception as e:
                print(f"[UPOZORENJE] {document_type.capitalize()} {broj} kreiran, ali mail nije poslan: {e}", file=sys.stderr)

    overlap = config.get("lookback_overlap_seconds", 180)
    new_watermark_dt = datetime.strptime(latest_updated_at, "%Y-%m-%dT%H:%M:%SZ") - timedelta(seconds=overlap)
    state.set_watermark(new_watermark_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    state.close()

    print(f"Gotovo. Novo fiskalizirano: {processed_count}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sinkronizira plaćene Cliniko račune u Solo.")
    parser.add_argument(
        "--backfill-days", type=int, default=None,
        help="Samo kod prvog pokretanja: koliko dana unatrag gledati plaćene račune.",
    )
    args = parser.parse_args()
    run(backfill_days=args.backfill_days)
