"""
Poprio: sinkronizacija Cliniko -> Solo.

Pronalazi novoplaćene Cliniko račune i fiskalizira ih preko Solo API-ja,
praktički u trenutku kad su plaćeni. Pamti stanje u SQLite bazi
(state_db_path) pa svaki Cliniko račun šalje u Solo točno jednom, bez
obzira koliko se puta skripta pokrene.

Dva načina rada (vidi README.md za detalje):
  python sync.py            - jedan prolaz, za pokretanje preko crona
  python sync.py --loop     - trajno radi kao servis (npr. pod systemd),
                               provjerava Cliniko svakih `poll_interval_seconds`
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from cliniko_client import ClinikoClient
from lock import AlreadyRunning, single_instance
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


def detect_nacin_placanja(invoice_id, invoice_items, config):
    """Cliniko API ne šalje način plaćanja kao posebno polje na računu, ali
    ga osoblje označava dodavanjem posebne stavke od 0 EUR na račun (npr.
    "Način plaćanja: Gotovina", šifra "GOT" postavljena kao item code te
    stavke u Cliniko Settings -> Billable items). Ova funkcija traži tu
    stavku po `code` polju svake stavke računa (točno podudaranje,
    case-insensitive) prema mapi `solo_nacin_placanja_item_codes` u
    config.json (Solo kod -> Cliniko item code). Ako nijedna stavka na
    računu ne odgovara, vraća `solo_nacin_placanja_default` i to jasno
    ispisuje u logu."""
    item_codes = {(item.get("code") or "").strip().upper() for item in invoice_items}
    for solo_code, cliniko_code in config["solo_nacin_placanja_item_codes"].items():
        if cliniko_code.strip().upper() in item_codes:
            return int(solo_code)

    default = config["solo_nacin_placanja_default"]
    print(
        f"[UPOZORENJE] Cliniko račun {invoice_id}: nijedna stavka računa ne "
        f"odgovara poznatoj šifri načina plaćanja, koristim zadani ({default})."
    )
    return default


def format_address(patient):
    """Sastavlja `kupac_adresa` za Solo iz standardnih Cliniko adresnih polja."""
    street = ", ".join(
        p for p in (patient.get("address_1"), patient.get("address_2")) if p
    )
    city_line = " ".join(
        p for p in (patient.get("post_code"), patient.get("city")) if p
    )
    return ", ".join(p for p in (street, city_line) if p) or None


def initialize_watermark(state, args):
    """Bez zapisa dokle je obrađeno skripta NE SMIJE ništa poslati.

    Prazna baza (nova instalacija, preseljen server, izgubljen Docker volumen)
    izgleda potpuno isto kao "ništa još nije fiskalizirano" - pa bi tiho poslala
    već fiskalizirane račune u Solo drugi put. Duplikat fiskalnog računa
    ispravlja se samo stornom, zato ovdje tražimo svjesnu odluku operatera
    umjesto da pretpostavimo bilo što."""
    if state.get_watermark():
        return True

    if args.init_from_now and args.backfill_days:
        print("[GREŠKA] Odaberi ili --init-from-now ili --backfill-days, ne oboje.", file=sys.stderr)
        return False

    if args.init_from_now:
        start = datetime.now(timezone.utc)
    elif args.backfill_days:
        start = datetime.now(timezone.utc) - timedelta(days=args.backfill_days)
    else:
        print(
            "[GREŠKA] Baza obrađenih računa je prazna - ne znam što je već poslano u Solo.\n"
            "\n"
            "Ako je baza izgubljena (preseljen server, Docker bez trajnog volumena), a ja\n"
            "krenem slati, već fiskalizirani računi otišli bi u Solo drugi put - a duplikat\n"
            "fiskalnog računa ispravlja se samo stornom. Zato stajem i pitam.\n"
            "\n"
            "Odaberi:\n"
            "  python sync.py --init-from-now     kreni od sada, ne diraj starije račune\n"
            "                                     (nakon preseljenja ili gubitka baze)\n"
            "  python sync.py --backfill-days 7   obradi i račune plaćene zadnjih 7 dana\n"
            "                                     (prva instalacija)\n",
            file=sys.stderr,
        )
        return False

    stamp = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    state.set_watermark(stamp)
    print(f"Inicijalizirano: obrađujem račune ažurirane nakon {stamp}")
    return True


def run_once(config, cliniko, solo, state):
    watermark = state.get_watermark()
    invoices = cliniko.get_paid_invoices(updated_since=watermark)
    print(f"Pronađeno {len(invoices)} plaćenih računa od {watermark}")

    latest_updated_at = watermark
    processed_count = 0

    for invoice in invoices:
        cliniko_id = invoice["id"]
        updated_at = invoice.get("updated_at", latest_updated_at)
        if updated_at > latest_updated_at:
            latest_updated_at = updated_at

        # Zauzmi račun prije slanja - vidi state.py za razlog. Ako ga je netko
        # već zauzeo ili obradio, preskačemo.
        if not state.claim(cliniko_id):
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
        invoice_items = cliniko.get_invoice_items(cliniko_id)
        nacin_placanja = detect_nacin_placanja(cliniko_id, invoice_items, config)

        # Oznaka izvornog Cliniko računa ostaje zapisana na samom Solo dokumentu
        # (vidljiva je i na PDF-u). Ako lokalna baza ikad zakaže, po njoj se
        # ručno vidi je li neki Cliniko račun već fiskaliziran.
        napomene = f"Cliniko #{cliniko_id}"

        try:
            if document_type == "ponuda":
                racun = solo.create_ponuda(
                    tip_kupca=config["solo_tip_kupca"],
                    tip_usluge=config["solo_tip_usluge"],
                    nacin_placanja=nacin_placanja,
                    kupac_naziv=patient_name or "Kupac",
                    kupac_oib=patient_oib,
                    kupac_adresa=patient_address,
                    napomene=napomene,
                    stavke=stavke,
                )
                broj = racun.get("broj_ponude")
            else:
                racun = solo.create_invoice(
                    tip_racuna=config["solo_tip_racuna"],
                    tip_kupca=config["solo_tip_kupca"],
                    tip_usluge=config["solo_tip_usluge"],
                    nacin_placanja=nacin_placanja,
                    kupac_naziv=patient_name or "Kupac",
                    kupac_oib=patient_oib,
                    kupac_adresa=patient_address,
                    napomene=napomene,
                    stavke=stavke,
                )
                broj = racun.get("broj_racuna")
        except (SoloAPIError, requests.exceptions.RequestException) as e:
            # requests.exceptions.RequestException hvata i prolazne mrežne/HTTP
            # greške (npr. Solo 502/503, timeout) - ne samo Solo-ove aplikacijske
            # greške - da jedan neuspjeh ne prekine obradu ostalih računa u istom
            # prolazu. Zauzimanje se otpušta pa se račun pokušava ponovno.
            state.release(cliniko_id)
            print(f"[GREŠKA] Cliniko račun {cliniko_id}: {e}", file=sys.stderr)
            continue

        state.mark_done(cliniko_id, racun)
        processed_count += 1
        print(f"Cliniko #{cliniko_id} -> Solo {document_type} {broj} "
              f"(način plaćanja {nacin_placanja}, JIR {racun.get('jir', '-')})")

        # Ponuda nije fiskalni dokument (nema JIR/ZKI) - pacijentu se šalje samo
        # kad je stvarno kreiran fiskalizirani racun, da slučajno ne dobije
        # nešto što izgleda kao račun, a nije.
        if document_type == "racun" and config.get("send_pdf_email") and patient_email and racun.get("pdf"):
            try:
                send_invoice_pdf(config, patient_email, patient_name, racun["pdf"], broj)
            except Exception as e:
                print(f"[UPOZORENJE] Račun {broj} kreiran, ali mail nije poslan: {e}", file=sys.stderr)

    overlap = config.get("lookback_overlap_seconds", 180)
    new_watermark_dt = datetime.strptime(latest_updated_at, "%Y-%m-%dT%H:%M:%SZ") - timedelta(seconds=overlap)
    state.set_watermark(new_watermark_dt.strftime("%Y-%m-%dT%H:%M:%SZ"))

    print(f"Gotovo. Novo fiskalizirano: {processed_count}.")
    return processed_count


def report_pending_claims(state):
    """Zapisi zaustavljeni u `pending` znače da je proces prekinut usred slanja
    - ne zna se je li dokument u Solu nastao. Automatsko ponavljanje bi moglo
    stvoriti duplikat, pa se traži ljudska provjera."""
    pending = state.pending_claims()
    if not pending:
        return

    print(
        "[UPOZORENJE] Računi zaustavljeni usred slanja: " + ", ".join(pending) + "\n"
        "  Proces je prekinut nakon što je račun zauzet, a prije potvrde da je\n"
        "  dokument nastao - ne zna se je li u Solu nastao ili nije. Neću ih\n"
        "  ponavljati sam jer bi mogao nastati duplikat fiskalnog računa.\n"
        "  Provjeri u Solu postoji li dokument s napomenom \"Cliniko #<id>\" i\n"
        "  razriješi prema uputama u README-u (sekcija \"Zaustavljeni računi\").",
        file=sys.stderr,
    )


def run_with_lock(config, args):
    cliniko = ClinikoClient(
        api_key=config["cliniko_api_key"],
        user_agent=config["cliniko_user_agent"],
    )
    solo = SoloClient(api_token=config["solo_api_token"])
    state = StateStore(config["state_db_path"])

    if not initialize_watermark(state, args):
        state.close()
        sys.exit(1)

    report_pending_claims(state)

    if not args.loop:
        run_once(config, cliniko, solo, state)
        state.close()
        return

    interval = config.get("poll_interval_seconds", 60)
    print(f"Poprio pokrenut u --loop modu, provjera svakih {interval}s. Ctrl+C za izlaz.")
    while True:
        try:
            run_once(config, cliniko, solo, state)
        except Exception as e:
            print(f"[GREŠKA] Prolaz sinkronizacije nije uspio: {e}", file=sys.stderr)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Sinkronizira plaćene Cliniko račune u Solo.")
    parser.add_argument(
        "--backfill-days", type=int, default=None,
        help="Kod inicijalizacije prazne baze: obradi i račune plaćene zadnjih N dana.",
    )
    parser.add_argument(
        "--init-from-now", action="store_true",
        help="Kod inicijalizacije prazne baze: kreni od sada, bez obrade ijednog starijeg računa.",
    )
    parser.add_argument(
        "--loop", action="store_true",
        help="Radi trajno (za pokretanje kao systemd servis) umjesto jednog prolaza za cron.",
    )
    args = parser.parse_args()

    config = load_config()
    lock_path = Path(config["state_db_path"]).with_suffix(".lock")

    try:
        with single_instance(lock_path):
            run_with_lock(config, args)
    except AlreadyRunning:
        print(
            f"Poprio već radi (zaključano {lock_path}) - ovaj pokušaj ne radi ništa.\n"
            "Ako ovo nije očekivano, provjeri imaš li i systemd servis i cron unos."
        )


if __name__ == "__main__":
    main()
