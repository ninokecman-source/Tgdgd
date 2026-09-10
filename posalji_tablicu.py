"""
Dan nakon završetka tečaja pošalje popunjenu Excel tablicu Emmett centrali.

Prođe kroz sve tablice u output_dir, iz svake pročita datume tečaja, i za
one koji su završili prije zadanog broja dana (po defaultu 1) pošalje mail
s tablicom u privitku - na adrese iz `course_report_to`.

Pokreće se iz crona jednom dnevno. Prije nego pustiš da stvarno šalje,
pogledaj što bi poslao:

    python3 posalji_tablicu.py --pregled

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

from send_reminders import (
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

    if xlsx_path.name in state:
        return False   # već poslano

    polaznici = read_participants(ws, find_totals_row(ws))
    if not polaznici:
        print(f"[!] {xlsx_path.name}: tečaj je završio, ali u tablici nema "
              f"nijednog polaznika - ne šaljem.")
        return False

    primatelji = config.get("course_report_to", [])
    if not primatelji:
        print("[!] U config.json nema 'course_report_to' - nemam kome slati.")
        return False

    varijable = dict(info, broj_polaznika=len(polaznici))
    naslov = config.get("course_report_subject", DEFAULT_SUBJECT).format(**varijable)
    tijelo = config.get("course_report_body", DEFAULT_BODY).format(**varijable)

    print(f"\n{info['course_code']} / {info['location']} ({info['dates']}) - "
          f"završio prije {proslo} dana, {len(polaznici)} polaznika")
    print(f"  za: {', '.join(primatelji)}")
    print(f"  privitak: {xlsx_path.name}")

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
    args = parser.parse_args()

    config = load_config()

    dry_run = args.pregled or not config.get("send_course_report")
    if dry_run and not args.pregled:
        print("send_course_report je isključen u config.json - radim samo pregled.\n")

    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    datoteke = sorted(p for p in output_dir.glob("*.xlsx") if not p.name.startswith("~$"))
    if not datoteke:
        print(f"Nema nijedne .xlsx tablice u {output_dir}.")
        return

    state = load_state()
    danas = date.today()
    poslano = sum(obradi_tablicu(p, config, state, danas, dry_run) for p in datoteke)

    print()
    if dry_run:
        print(f"Pregled gotov ({len(datoteke)} tablica) - ništa nije poslano.")
    else:
        print(f"Gotovo. Poslano {poslano} tablica od {len(datoteke)} pregledanih.")


if __name__ == "__main__":
    main()
