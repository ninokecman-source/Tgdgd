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

from alerts import Alerter
from cliniko_client import ClinikoClient
from lock import AlreadyRunning, single_instance
from solo_client import SoloClient
from state import StateStore
from mailer import send_invoice_pdf

CONFIG_PATH = Path(__file__).parent / "config.json"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Koliko prolaza zaredom smije pasti prije nego se javi mailom. Jedan pad je
# obično prolazan (mreža, Solo 502) i ne treba buditi nikoga.
FAILED_PASSES_BEFORE_ALERT = 3

# Solo prima najviše 36 stavki po računu (greška 107).
SOLO_MAX_STAVKI = 36


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


def extract_billable_item_id(item):
    """ID kataloške stavke iz koje je nastala ova stavka računa."""
    link = (item.get("billable_item") or {}).get("links", {}).get("self", "")
    match = re.search(r"/billable_items/(\d+)", link)
    return match.group(1) if match else None


def marker_item_ids(config):
    return {str(v).strip() for v in config["solo_nacin_placanja_item_ids"].values()}


def detect_nacin_placanja(invoice_id, invoice_items, config):
    """Cliniko API ne šalje način plaćanja kao posebno polje na računu, ali ga
    osoblje označava dodavanjem posebne stavke od 0 EUR na račun (npr. "Način
    plaćanja: Gotovina").

    Prepoznaje se po ID-u kataloške stavke, ne po njenoj šifri ili nazivu:
    Cliniko šifre dodjeljuje iz istog brojčanog niza kojim numerira i obične
    usluge, pa bi se buduća usluga mogla sudariti s oznakom - a ID je trajan i
    jedinstven i preživi preimenovanje stavke.

    Ako nijedna stavka na računu ne odgovara, vraća `solo_nacin_placanja_default`
    i to jasno ispisuje u logu."""
    present = {extract_billable_item_id(item) for item in invoice_items}
    for solo_code, billable_item_id in config["solo_nacin_placanja_item_ids"].items():
        if str(billable_item_id).strip() in present:
            return int(solo_code)

    default = config["solo_nacin_placanja_default"]
    print(
        f"[UPOZORENJE] Cliniko račun {invoice_id}: nijedna stavka računa nije "
        f"oznaka načina plaćanja, koristim zadani ({default})."
    )
    return default


class NothingToInvoice(Exception):
    """Na računu nema nijedne stvarne stavke - nema se što fiskalizirati."""


def line_total(item):
    """Iznos retka koji je pacijent stvarno platio - nakon popusta, s porezom."""
    total = item.get("total_including_tax")
    if total is not None:
        return float(total)
    # Rezerva ako Cliniko ne pošalje izračunat iznos retka.
    gross = float(item.get("unit_price") or 0) * float(item.get("quantity") or 1)
    return gross - float(item.get("discounted_amount") or 0)


def build_stavke(config, invoice, invoice_items):
    """Pretvara stvarne stavke Cliniko računa u stavke za Solo.

    Na fiskalni račun moraju ići stvarne usluge, ne jedna zbirna stavka. Solo
    očekuje NETO cijenu po jedinici i sam dodaje porez, a Cliniko daje iznos
    retka s porezom i nakon popusta - pa se računa unatrag.

    Popust se ne prenosi kao zaseban podatak nego je već sadržan u cijeni
    (`popust_x` u Solu je postotak, a Cliniko popust može biti i u eurima;
    pretvaranje bi zbog zaokruživanja lako promijenilo ukupan iznos).

    Diže iznimku ako se zbroj stavki ne poklapa s ukupnim iznosom računa -
    bolje ne fiskalizirati ništa nego fiskalizirati krivi iznos."""
    markers = marker_item_ids(config)
    tax_rate = config["solo_default_tax_rate"]
    fallback_opis = config["solo_default_service_description"]

    stavke = []
    for item in invoice_items:
        # Oznaka načina plaćanja je pomoćna stavka od 0 EUR - služi samo za
        # prepoznavanje, na računu u Solu nema što tražiti.
        if extract_billable_item_id(item) in markers:
            continue

        quantity = float(item.get("quantity") or 1)
        if quantity <= 0:
            raise ValueError(f"stavka '{item.get('name')}' ima količinu {quantity}")

        net_line = line_total(item) / (1 + tax_rate / 100)
        stavke.append({
            "opis": (item.get("name") or fallback_opis)[:500],
            "cijena": round(net_line / quantity, 2),
            "kolicina": quantity,
            "porez_stopa": tax_rate,
        })

    if not stavke:
        raise NothingToInvoice("račun nema nijednu stavku osim oznake načina plaćanja")

    if len(stavke) > SOLO_MAX_STAVKI:
        raise ValueError(
            f"račun ima {len(stavke)} stavki, Solo prima najviše {SOLO_MAX_STAVKI}"
        )

    # Ono što će Solo izračunati mora biti isto što je pacijent platio u Clinku.
    # Ako nije, negdje se izgubio popust, koncesija ili cent na zaokruživanju -
    # i taj račun ne smije ići u fiskalizaciju dok se ne pogleda.
    expected = float(invoice.get("total_amount"))
    computed = round(
        sum(s["cijena"] * s["kolicina"] for s in stavke) * (1 + tax_rate / 100), 2
    )
    if abs(computed - expected) >= 0.005:
        raise ValueError(
            f"zbroj stavki ({computed:.2f}) ne odgovara iznosu računa ({expected:.2f})"
        )

    return stavke


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

    stamp = start.strftime(ISO_FORMAT)
    state.set_watermark(stamp)
    print(f"Inicijalizirano: obrađujem račune ažurirane nakon {stamp}")
    return True


def report_failure(config, state, cliniko_id, error, alerter=None):
    """Bilježi neuspjeh i javlja ga - glasnije kad su pokušaji potrošeni."""
    max_attempts = config.get("max_retry_attempts", 5)
    attempts = state.mark_failed(cliniko_id, error)

    if attempts >= max_attempts:
        print(
            f"[PAŽNJA] Cliniko račun {cliniko_id}: neuspjeh {attempts}/{max_attempts} - "
            f"prestajem pokušavati.\n"
            f"  Greška: {error}\n"
            f"  Račun NIJE fiskaliziran i neće se ponoviti sam. Riješi uzrok pa ponovno\n"
            f"  omogući pokušaje (README, sekcija \"Zaglavljeni računi\").",
            file=sys.stderr,
        )
        if alerter:
            alerter.problem(
                f"exhausted:{cliniko_id}",
                f"Račun nije fiskaliziran ({cliniko_id})",
                f"Cliniko račun {cliniko_id} nije uspio otići u Solo ni nakon "
                f"{attempts} pokušaja, pa sam prestao pokušavati.\n\n"
                f"Greška: {error}\n\n"
                f"Taj račun NIJE fiskaliziran. Riješi uzrok pa ga vrati u red za "
                f"slanje prema uputama u README-u (sekcija \"Zaglavljeni računi\").",
            )
    else:
        print(
            f"[GREŠKA] Cliniko račun {cliniko_id} (pokušaj {attempts}/{max_attempts}): {error}",
            file=sys.stderr,
        )


def process_invoice(config, cliniko, solo, state, invoice, alerter=None):
    """Šalje jedan već zauzet račun u Solo. Vraća True ako je dokument nastao.

    Račun je u ovom trenutku zauzet (status `pending`), pa SVAKI izlaz odavde
    mora taj status razriješiti - inače ostaje zaglavljen i traži ručnu
    intervenciju. Zato je hvatanje grešaka namjerno široko."""
    cliniko_id = invoice["id"]
    document_type = config.get("solo_document_type", "racun")

    try:
        patient_id = extract_patient_id(invoice)
        patient = cliniko.get_patient(patient_id) if patient_id else {}
        patient_name = f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip()
        patient_email = patient.get("email")
        patient_oib = extract_oib(patient)
        patient_address = format_address(patient)

        invoice_items = cliniko.get_invoice_items(cliniko_id)
        nacin_placanja = detect_nacin_placanja(cliniko_id, invoice_items, config)
        stavke = build_stavke(config, invoice, invoice_items)

        # Oznaka izvornog Cliniko računa ostaje zapisana na samom Solo dokumentu
        # (vidljiva je i na PDF-u). Ako lokalna baza ikad zakaže, po njoj se
        # ručno vidi je li neki Cliniko račun već fiskaliziran.
        napomene = f"Cliniko #{cliniko_id}"

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
    except NothingToInvoice as e:
        # Nije greška nego račun bez sadržaja (npr. samo oznaka načina plaćanja).
        # Ponavljanje ne bi ništa promijenilo, pa se zatvara kao preskočen.
        state.mark_skipped(cliniko_id, e)
        print(f"[PRESKOČENO] Cliniko račun {cliniko_id}: {e}")
        return False
    except Exception as e:
        report_failure(config, state, cliniko_id, e, alerter)
        return False

    broj = racun.get("broj_racuna") or racun.get("broj_ponude")
    state.mark_done(cliniko_id, racun)
    print(f"Cliniko #{cliniko_id} -> Solo {document_type} {broj} "
          f"({len(stavke)} stavki, način plaćanja {nacin_placanja}, "
          f"JIR {racun.get('jir', '-')})")

    # Ponuda nije fiskalni dokument (nema JIR/ZKI) - pacijentu se šalje samo
    # kad je stvarno kreiran fiskalizirani racun, da slučajno ne dobije
    # nešto što izgleda kao račun, a nije.
    if document_type == "racun" and config.get("send_pdf_email") and patient_email and racun.get("pdf"):
        try:
            send_invoice_pdf(config, patient_email, patient_name, racun["pdf"], broj)
        except Exception as e:
            print(f"[UPOZORENJE] Račun {broj} kreiran, ali mail nije poslan: {e}", file=sys.stderr)

    return True


def retry_failed(config, cliniko, solo, state, alerter=None):
    """Ponovno pokušava ranije neuspjele račune - po ID-u, neovisno o tome jesu
    li još unutar vremenskog prozora upita prema Clinku. Bez ovoga bi račun koji
    padne dok je Solo nedostupan tiho ispao čim oznaka odmakne preko njega."""
    processed = 0
    for cliniko_id in state.failed_for_retry(config.get("max_retry_attempts", 5)):
        if not state.claim_retry(cliniko_id):
            continue
        try:
            invoice = cliniko.get_invoice(cliniko_id)
        except Exception as e:
            report_failure(config, state, cliniko_id, e, alerter)
            continue
        if process_invoice(config, cliniko, solo, state, invoice, alerter):
            processed += 1
    return processed


def advance_watermark(state, previous, latest_seen, config):
    """Pomiče oznaku "obrađeno do", ali NIKAD unatrag.

    Preklapanje (`lookback_overlap_seconds`) namjerno vraća oznaku malo iza
    najnovijeg viđenog računa, da se ne propusti račun koji stigne s malim
    zakašnjenjem. Ali kad u prolazu nema nijednog računa, najnoviji viđeni je
    sama dosadašnja oznaka - pa bi oduzimanje preklapanja gurnulo oznaku unatrag,
    i tako svaki prolaz iznova (u --loop modu 180s svakih 15s). Zato uzimamo
    kasniji od dvaju datuma."""
    overlap = config.get("lookback_overlap_seconds", 180)
    candidate = datetime.strptime(latest_seen, ISO_FORMAT) - timedelta(seconds=overlap)
    state.set_watermark(max(candidate.strftime(ISO_FORMAT), previous))


def run_once(config, cliniko, solo, state, alerter=None):
    processed_count = retry_failed(config, cliniko, solo, state, alerter)

    watermark = state.get_watermark()
    invoices = cliniko.get_paid_invoices(updated_since=watermark)
    print(f"Pronađeno {len(invoices)} plaćenih računa od {watermark}")

    latest_updated_at = watermark

    for invoice in invoices:
        updated_at = invoice.get("updated_at", latest_updated_at)
        if updated_at > latest_updated_at:
            latest_updated_at = updated_at

        # Zauzmi račun prije slanja - vidi state.py za razlog. Ako ga je netko
        # već zauzeo, obradio ili je ranije pao (pa ide kroz retry_failed),
        # preskačemo.
        if not state.claim(invoice["id"]):
            continue

        if process_invoice(config, cliniko, solo, state, invoice, alerter):
            processed_count += 1

    advance_watermark(state, watermark, latest_updated_at, config)

    max_attempts = config.get("max_retry_attempts", 5)
    summary = f"Gotovo. Novo poslano: {processed_count}."
    waiting = len(state.failed_for_retry(max_attempts))
    stuck = len(state.exhausted_failures(max_attempts))
    if waiting:
        summary += f" Čeka ponovni pokušaj: {waiting}."
    if stuck:
        summary += f" Zaglavljeno: {stuck}."
    print(summary)
    return processed_count


def verify_payment_markers(config, cliniko, alerter):
    """Provjerava da oznake načina plaćanja iz configa stvarno postoje u Clinku.

    Ako je oznaka obrisana ili je u config upisan krivi ID, prepoznavanje tiho
    pada na zadani način plaćanja - a to je kriv podatak na fiskalnom računu.
    Zato se provjerava jednom pri pokretanju i ispisuje na što se koji Solo kod
    zapravo veže."""
    naziv_koda = {1: "transakcijski", 2: "gotovina", 3: "kartice", 4: "ček", 5: "ostalo"}
    try:
        katalog = {str(b["id"]): b for b in cliniko.get_billable_items()}
    except Exception as e:
        print(f"[UPOZORENJE] Nisam uspio provjeriti oznake načina plaćanja: {e}",
              file=sys.stderr)
        return

    nedostaju = []
    for solo_code, billable_item_id in config["solo_nacin_placanja_item_ids"].items():
        stavka = katalog.get(str(billable_item_id).strip())
        opis = naziv_koda.get(int(solo_code), solo_code)
        if not stavka:
            nedostaju.append(f"{opis} (ID {billable_item_id})")
            continue
        cijena = float(stavka.get("price") or 0)
        upozorenje = "  <- cijena nije 0!" if cijena else ""
        print(f"  oznaka {opis}: {stavka.get('name')!r} ({cijena:.2f} EUR){upozorenje}")

    if nedostaju:
        poruka = (
            "Ove oznake načina plaćanja iz config.json ne postoje u Clinku:\n\n"
            + "\n".join(f"  {n}" for n in nedostaju)
            + "\n\nRačuni s tim načinom plaćanja bit će fiskalizirani sa zadanim "
              "načinom, što je kriv podatak. Provjeri ID-eve naredbom:\n"
              "  python sync.py --list-billable-items"
        )
        print(f"[UPOZORENJE] {poruka}", file=sys.stderr)
        alerter.problem("markers_missing", "Oznake načina plaćanja ne postoje", poruka)
    else:
        alerter.resolved(
            "markers_missing",
            "Oznake načina plaćanja ponovno u redu",
            "Sve oznake načina plaćanja iz config.json ponovno postoje u Clinku.",
        )


def list_billable_items(config):
    """Ispisuje katalog usluga s ID-evima - za popunjavanje
    `solo_nacin_placanja_item_ids` u config.json."""
    cliniko = ClinikoClient(
        api_key=config["cliniko_api_key"],
        user_agent=config["cliniko_user_agent"],
    )
    print(f"{'ID':<22} {'šifra':<8} {'cijena':>9}  naziv")
    for b in sorted(cliniko.get_billable_items(), key=lambda x: float(x.get("price") or 0)):
        print(f"{b['id']:<22} {str(b.get('item_code') or ''):<8} "
              f"{float(b.get('price') or 0):>9.2f}  {b.get('name')}")
    print("\nStavke s cijenom 0.00 su kandidati za oznake načina plaćanja.")


def ping_healthcheck(config):
    """Javlja vanjskom nadzoru da je prolaz prošao.

    Ovo je jedino što može otkriti da je sama skripta prestala raditi - mrtav
    proces, ugašen server ili pukla mreža ne mogu poslati mail o sebi. Servis
    poput healthchecks.io šalje obavijest kad ovi javljanja prestanu stizati."""
    url = (config.get("healthcheck_url") or "").strip()
    if not url:
        return
    try:
        requests.get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"[UPOZORENJE] Javljanje vanjskom nadzoru nije prošlo: {e}", file=sys.stderr)


def run_pass(config, cliniko, solo, state, alerter):
    """Jedan prolaz sa svime što ide oko njega: brojanje uzastopnih kvarova,
    obavijesti i javljanje vanjskom nadzoru."""
    try:
        run_once(config, cliniko, solo, state, alerter)
    except Exception as e:
        failures = state.get_int("consecutive_failures") + 1
        state.set_int("consecutive_failures", failures)
        print(f"[GREŠKA] Prolaz sinkronizacije nije uspio ({failures}. zaredom): {e}",
              file=sys.stderr)
        if failures >= FAILED_PASSES_BEFORE_ALERT:
            alerter.problem(
                "sync_failure",
                "Fiskalizacija ne radi",
                f"Sinkronizacija Cliniko -> Solo nije uspjela {failures} puta zaredom.\n\n"
                f"Zadnja greška: {e}\n\n"
                f"Dok ovo traje, plaćeni računi se NE fiskaliziraju. Računi se ne gube - "
                f"poslat će se kad veza proradi - ali provjeri uzrok (istekao API ključ, "
                f"Solo nedostupan, pukla mreža).",
            )
        return False

    if state.get_int("consecutive_failures"):
        state.set_int("consecutive_failures", 0)
        alerter.resolved(
            "sync_failure",
            "Fiskalizacija ponovno radi",
            "Sinkronizacija Cliniko -> Solo je ponovno uspjela. Računi koji su čekali "
            "su u međuvremenu poslani.",
        )
    ping_healthcheck(config)
    return True


def report_stuck_invoices(state, config, alerter):
    """Računi koji traže ljudsku pažnju - javljaju se pri svakom pokretanju."""
    pending = state.pending_claims()
    if pending:
        alerter.problem(
            "pending:" + ",".join(pending),
            "Računi zaustavljeni usred slanja",
            "Ovi Cliniko računi zaustavljeni su usred slanja u Solo:\n\n"
            + "\n".join(f"  {p}" for p in pending)
            + "\n\nNe zna se je li dokument u Solu nastao ili nije, pa ih ne ponavljam "
              "sam (mogao bi nastati duplikat fiskalnog računa). Provjeri u Solu postoji "
              "li dokument s napomenom \"Cliniko #<id>\" i razriješi prema README-u "
              "(sekcija \"Zaustavljeni računi\").",
        )
        print(
            "[UPOZORENJE] Računi zaustavljeni usred slanja: " + ", ".join(pending) + "\n"
            "  Proces je prekinut nakon što je račun zauzet, a prije potvrde da je\n"
            "  dokument nastao - ne zna se je li u Solu nastao ili nije. Neću ih\n"
            "  ponavljati sam jer bi mogao nastati duplikat fiskalnog računa.\n"
            "  Provjeri u Solu postoji li dokument s napomenom \"Cliniko #<id>\" i\n"
            "  razriješi prema uputama u README-u (sekcija \"Zaustavljeni računi\").",
            file=sys.stderr,
        )

    exhausted = state.exhausted_failures(config.get("max_retry_attempts", 5))
    if exhausted:
        print(
            "[UPOZORENJE] Računi koji su potrošili sve pokušaje i NISU fiskalizirani:",
            file=sys.stderr,
        )
        for cliniko_id, attempts, last_error in exhausted:
            print(f"  {cliniko_id} ({attempts} pokušaja) — {last_error}", file=sys.stderr)
        print(
            "  Riješi uzrok pa ponovno omogući pokušaje (README, \"Zaglavljeni računi\").",
            file=sys.stderr,
        )


def run_with_lock(config, args):
    cliniko = ClinikoClient(
        api_key=config["cliniko_api_key"],
        user_agent=config["cliniko_user_agent"],
    )
    solo = SoloClient(api_token=config["solo_api_token"])
    state = StateStore(config["state_db_path"])
    alerter = Alerter(config, state)

    if not alerter.enabled:
        print("[UPOZORENJE] `alert_email` nije postavljen - ako fiskalizacija stane, "
              "nitko o tome neće biti obaviješten.", file=sys.stderr)

    if not initialize_watermark(state, args):
        state.close()
        sys.exit(1)

    verify_payment_markers(config, cliniko, alerter)
    report_stuck_invoices(state, config, alerter)

    if not args.loop:
        run_pass(config, cliniko, solo, state, alerter)
        state.close()
        return

    interval = config.get("poll_interval_seconds", 60)
    print(f"Poprio pokrenut u --loop modu, provjera svakih {interval}s. Ctrl+C za izlaz.")
    while True:
        run_pass(config, cliniko, solo, state, alerter)
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
    parser.add_argument(
        "--list-billable-items", action="store_true",
        help="Ispiši katalog usluga iz Clinika s ID-evima i izađi (za popunjavanje configa).",
    )
    args = parser.parse_args()

    config = load_config()

    if args.list_billable_items:
        list_billable_items(config)
        return
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
