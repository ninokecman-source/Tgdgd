"""
Dan nakon završetka tečaja pošalje popunjenu Excel tablicu Emmett centrali.

Prođe kroz sve tablice u output_dir, iz svake pročita datume tečaja, i za
one koji su završili prije zadanog broja dana (po defaultu 1) pošalje mail
s tablicom u privitku - na adrese iz `course_report_to`.

Pokreće se iz crona jednom dnevno. Prije nego pustiš da stvarno šalje,
pogledaj što bi poslao:

    python3 posalji_tablicu.py --pregled

Tekst maila stoji u dokumentu 'izvjestaj centrali.docx' uz tablice (isto
kao podsjetnici); ako ga nema, koristi se tekst iz configa odnosno ugrađeni.
Uključuje se u config.json s "send_course_report": true. Skripta pamti koje
je tablice već poslala (sent_reports.json), pa se ista ne šalje dvaput.

Tablica sadrži osobne podatke polaznika (ime, adresa, email, telefon) -
šalje se Emmett centrali jer je to njihov administrativni obrazac.
"""

import argparse
import json
import mimetypes
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from openpyxl import load_workbook

import predlosci
from send_reminders import (
    FIRST_PARTICIPANT_ROW,
    course_info,
    find_totals_row,
    parse_course_dates,
    read_participants,
)
from zoho_to_excel import load_config, with_retry

STATE_PATH = Path(__file__).with_name("sent_reports.json")

DEFAULT_SUBJECT = ("Emmett Technique {course_code} - {location}, {dates} - "
                   "course administration sheet")

DEFAULT_BODY = """Hi Ozren and Heidi,

The {course_code} course in {location} wrapped up yesterday ({dates}), with {broj_polaznika} participants in total.

Please find the completed administration sheet attached.

Do let me know if anything needs correcting, or if you would like it in a different format.

Kind regards,
{instructor_name}
Emmett Technique Instructor, Croatia
"""

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def provjeri_potpunost(ws, info: dict, polaznici: list) -> list:
    """Vrati popis onoga što u tablici nedostaje. Provjerava se ono što se
    popunjava ručno (uplate, PDV) i zaglavlje tečaja - dakle sve što
    skripte same ne upišu, pa lako ostane prazno. Dvorana se ne gleda: ona
    stoji u dokumentu o lokaciji, ne u tablici."""
    fali = []

    for oznaka, polje in [("Kod tečaja (C4)", "course_code"),
                          ("Mjesto (C5)", "location"),
                          ("Datumi (C6)", "dates"),
                          ("Instruktor (M4)", "instructor_name")]:
        if not info.get(polje):
            fali.append(f"{oznaka} je prazno")

    totals_row = find_totals_row(ws)
    pdv = ws.cell(row=totals_row + 2, column=11).value
    if pdv in (None, ""):
        fali.append(f"PDV % (K{totals_row + 2}) nije upisan")

    # Redci se gledaju izravno, a ne preko popisa polaznika: tako se uhvati i
    # netko tko je u tablicu upisan ručno, bez email adrese.
    neplaceni, bez_maila = [], []
    for row in range(FIRST_PARTICIPANT_ROW, totals_row):
        ime = ws.cell(row=row, column=2).value
        if not ime:
            continue
        puno_ime = f"{ime} {ws.cell(row=row, column=3).value or ''}".strip()
        if not ws.cell(row=row, column=12).value:
            neplaceni.append(puno_ime)
        if not ws.cell(row=row, column=8).value:
            bez_maila.append(puno_ime)

    if neplaceni:
        fali.append(f"Payment Received nije upisan za: {', '.join(neplaceni)}")
    if bez_maila:
        fali.append(f"Nema email adrese za: {', '.join(bez_maila)}")

    return fali


def javi_nepotpunu(config: dict, xlsx_path: Path, info: dict, fali: list,
                    broj_polaznika: int) -> None:
    """Pošalje TEBI mail da tablica nije spremna za slanje centrali."""
    tijelo = (
        f"Tečaj {info['course_code']} / {info['location']} ({info['dates']}) je završio, "
        f"ali tablica nije potpuna pa NIJE poslana centrali.\n\n"
        f"Datoteka: {xlsx_path}\n"
        f"Polaznika: {broj_polaznika}\n\n"
        f"Nedostaje:\n" + "\n".join(f"  - {x}" for x in fali) +
        "\n\nKad to popuniš, tablica će se poslati sama pri sljedećem prolasku "
        "(jednom dnevno).\n"
    )

    msg = EmailMessage()
    msg["Subject"] = (f"⚠️ Tablica nije potpuna - {info['course_code']} "
                      f"{info['location']} nije poslana centrali")
    msg["From"] = config["zoho_email"]
    msg["To"] = config.get("notify_email", config["zoho_email"])
    msg.set_content(tijelo)

    def _posalji():
        with smtplib.SMTP_SSL(config["smtp_host"], config.get("smtp_port", 465)) as smtp:
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)

    with_retry(_posalji)


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def posalji(config: dict, primatelji: list, naslov: str, tijelo: str,
            xlsx_path: Path) -> None:
    msg = EmailMessage()
    msg["Subject"] = naslov
    msg["From"] = config["zoho_email"]
    msg["To"] = ", ".join(primatelji)
    msg["Cc"] = config["zoho_email"]      # kopija tebi, da imaš trag u Sentu
    msg.set_content(tijelo)

    podaci = xlsx_path.read_bytes()
    tip, _ = mimetypes.guess_type(xlsx_path.name)
    glavni, _, pod = (tip or XLSX_MIME).partition("/")
    msg.add_attachment(podaci, maintype=glavni, subtype=pod or "octet-stream",
                       filename=xlsx_path.name)

    def _posalji():
        with smtplib.SMTP_SSL(config["smtp_host"], config.get("smtp_port", 465)) as smtp:
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)

    with_retry(_posalji)


def obradi_tablicu(xlsx_path: Path, config: dict, state: dict, danas: date,
                    dry_run: bool) -> bool:
    """Vrati True ako je tablica poslana (ili bi bila, u pregledu)."""
    wb = with_retry(lambda: load_workbook(xlsx_path), retry_on=(PermissionError, OSError))
    if "podaci" not in wb.sheetnames:
        return False
    ws = wb["podaci"]

    info = course_info(ws, config)
    pocetak, kraj = parse_course_dates(info["dates"])
    if kraj is None:
        print(f"[!] {xlsx_path.name}: ne mogu pročitati datum tečaja "
              f"({info['dates']!r}), preskačem.")
        return False

    dana_nakon = config.get("course_report_days_after", 1)
    proslo = (danas - kraj).days

    if proslo < dana_nakon:
        return False   # tečaj još traje ili je prerano

    if state.get(xlsx_path.name, {}).get("poslano"):
        return False   # već poslano centrali

    polaznici = read_participants(ws, find_totals_row(ws))
    if not polaznici:
        print(f"[!] {xlsx_path.name}: tečaj je završio, ali u tablici nema "
              f"nijednog polaznika - ne šaljem.")
        return False

    primatelji = config.get("course_report_to", [])
    if not primatelji:
        print("[!] U config.json nema 'course_report_to' - nemam kome slati.")
        return False

    # Nepotpuna tablica ne ide centrali - radije javi sebi da je dopuniš.
    fali = provjeri_potpunost(ws, info, polaznici)
    if fali:
        print(f"\n[!] {xlsx_path.name}: tečaj je završio, ali tablica NIJE POTPUNA - "
              f"ne šaljem centrali. Nedostaje:")
        for stavka in fali:
            print(f"      - {stavka}")

        # Javi ti mailom, ali ne svaki dan istu stvar: samo kad se popis
        # nedostataka promijeni (npr. popunio si dvoranu, uplate još fale).
        zapis = state.get(xlsx_path.name, {})
        if dry_run:
            print("      (u pregledu ne šaljem obavijest)")
        elif zapis.get("nedostaje") == fali:
            print("      (već sam ti javio isto - ne šaljem opet)")
        else:
            javi_nepotpunu(config, xlsx_path, info, fali, len(polaznici))
            state[xlsx_path.name] = {"nepotpuno_od": danas.isoformat(), "nedostaje": fali}
            save_state(state)
            print(f"      Poslana obavijest tebi na "
                  f"{config.get('notify_email', config['zoho_email'])}")
        return False

    varijable = dict(info, broj_polaznika=len(polaznici))
    naslov, tijelo, izvor = predlosci.dohvati(
        xlsx_path.parent, "izvjestaj centrali", config=config,
        kljuc_naslov="course_report_subject", kljuc_tijela="course_report_body",
        zadani_naslov=DEFAULT_SUBJECT, zadano_tijelo=DEFAULT_BODY)
    naslov = naslov.format(**varijable)
    tijelo = tijelo.format(**varijable)

    print(f"\n{info['course_code']} / {info['location']} ({info['dates']}) - "
          f"završio prije {proslo} dana, {len(polaznici)} polaznika")
    print(f"  za: {', '.join(primatelji)}")
    print(f"  privitak: {xlsx_path.name}")
    print(f"  tekst: {izvor}")

    if dry_run:
        print("  --- poruka ---")
        print("  Naslov:", naslov)
        for redak in tijelo.splitlines():
            print("  " + redak)
        return True

    posalji(config, primatelji, naslov, tijelo, xlsx_path)
    state[xlsx_path.name] = {
        "poslano": danas.isoformat(),
        "tecaj": f"{info['course_code']} / {info['location']}",
        "datumi": info["dates"],
        "polaznika": len(polaznici),
        "primatelji": primatelji,
    }
    save_state(state)
    print(f"  POSLANO na {', '.join(primatelji)}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Pošalje popunjenu tablicu Emmett centrali nakon tečaja.")
    parser.add_argument("--pregled", action="store_true",
                        help="Samo prikaži što bi poslao, bez slanja")
    parser.add_argument("--datum", metavar="GGGG-MM-DD",
                        help="Odradi pregled kao da je taj datum - da vidiš kako će "
                             "mail izgledati prije nego tečaj stvarno završi "
                             "(radi samo uz --pregled)")
    args = parser.parse_args()

    if args.datum and not args.pregled:
        sys.exit("--datum se smije koristiti samo uz --pregled, da se ne bi "
                 "nešto poslalo prije vremena.")

    config = load_config()

    dry_run = args.pregled or not config.get("send_course_report")
    if dry_run and not args.pregled:
        print("send_course_report je isključen u config.json - radim samo pregled.\n")

    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    datoteke = sorted(p for p in output_dir.glob("*.xlsx") if not p.name.startswith("~$")
                      and p.name != "template_admin_sheet.xlsx")
    if not datoteke:
        print(f"Nema nijedne .xlsx tablice u {output_dir}.")
        return

    state = load_state()
    if args.datum:
        try:
            danas = date.fromisoformat(args.datum)
        except ValueError:
            sys.exit(f"Neispravan datum: {args.datum!r} - očekujem oblik 2026-10-05.")
        print(f"Pregled kao da je {danas.strftime('%d.%m.%Y.')}\n")
    else:
        danas = date.today()
    poslano = sum(obradi_tablicu(p, config, state, danas, dry_run) for p in datoteke)

    print()
    if dry_run:
        print(f"Pregled gotov ({len(datoteke)} tablica) - ništa nije poslano.")
    else:
        print(f"Gotovo. Poslano {poslano} tablica od {len(datoteke)} pregledanih.")


if __name__ == "__main__":
    main()
