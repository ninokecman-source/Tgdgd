"""
Automatski podsjetnici polaznicima prije tečaja.

Prođe kroz sve Excel tablice u output_dir, iz svake pročita datum tečaja
i sve upisane polaznike, pa onima kojima je tečaj za N dana pošalje
odgovarajući podsjetnik (npr. 10 dana prije - lokacija i što ponijeti,
1 dan prije - kratki podsjetnik da tečaj počinje sutra).

Pokreće se iz crona jednom dnevno, uz zoho_to_excel.py:
    0 8 * * * cd /putanja/do/foldera && /usr/bin/python3 send_reminders.py >> log.txt 2>&1

Prije nego pustiš da šalje stvarno, provjeri što bi poslao:
    python send_reminders.py --pregled

Poruke i rokovi se podešavaju u config.json (polje "reminders"), a slanje
se uključuje s "send_reminders": true. Skripta pamti kome je koji
podsjetnik poslala (sent_reminders.json), pa nitko ne dobiva istu poruku
dvaput, koliko god puta se skripta pokrenula.
"""

import argparse
import json
import re
import smtplib
import sys
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from openpyxl import load_workbook

from zoho_to_excel import (
    FIRST_PARTICIPANT_ROW,
    find_totals_row,
    load_config,
    with_retry,
)

STATE_PATH = Path(__file__).with_name("sent_reminders.json")

COL_FIRST_NAME = 2
COL_LAST_NAME = 3
COL_EMAIL = 8

# Zaglavlje tablice: kod tečaja, mjesto, datumi, instruktor, dvorana
CELL_COURSE_CODE = "C4"
CELL_LOCATION = "C5"
CELL_DATES = "C6"
CELL_INSTRUCTOR = "M4"
CELL_VENUE = "M5"


def parse_start_date(dates_text: str):
    """Iz zapisa datuma tečaja izvuče datum PRVOG dana. Emmettovi mailovi
    koriste razne oblike, pa se gleda samo niz brojeva u tekstu:

        '18.-19.01.2025.'    -> [18, 19, 1, 2025]        -> 18.01.2025
        '22-23.03.2025.'     -> [22, 23, 3, 2025]        -> 22.03.2025
        '30.11.-01.12.2024.' -> [30, 11, 1, 12, 2024]    -> 30.11.2024
        '18/19.01.2025.'     -> [18, 19, 1, 2025]        -> 18.01.2025
        '03.10.2026.'        -> [3, 10, 2026]            -> 03.10.2026

    Vraća None ako se datum ne može pouzdano pročitati - tada se za taj
    tečaj ništa ne šalje (bolje ne poslati nego poslati u krivi dan)."""
    if not dates_text:
        return None

    numbers = [int(n) for n in re.findall(r"\d+", str(dates_text))]
    if len(numbers) < 3 or numbers[-1] < 1000:
        return None  # bez četveroznamenkaste godine na kraju nema sigurnog čitanja

    year = numbers[-1]
    rest = numbers[:-1]

    if len(rest) == 2:            # d, m
        day, month = rest
    elif len(rest) == 3:          # d1, d2, m  (isti mjesec)
        day, month = rest[0], rest[2]
    elif len(rest) == 4:          # d1, m1, d2, m2  (prelazi mjesec)
        day, month = rest[0], rest[1]
        # Godina u zapisu pripada drugom datumu. Ako tečaj prelazi Novu
        # godinu (npr. '31.12.-01.01.2027.'), prvi dan je godinu ranije.
        if month > rest[3]:
            year -= 1
    else:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


def read_participants(ws, totals_row: int) -> list:
    participants = []
    for row in range(FIRST_PARTICIPANT_ROW, totals_row):
        email = ws.cell(row=row, column=COL_EMAIL).value
        email = str(email).strip() if email else ""
        if "@" not in email:
            continue
        participants.append({
            "first_name": str(ws.cell(row=row, column=COL_FIRST_NAME).value or "").strip(),
            "last_name": str(ws.cell(row=row, column=COL_LAST_NAME).value or "").strip(),
            "email": email,
        })
    return participants


def course_info(ws, config: dict) -> dict:
    def cell(ref):
        return str(ws[ref].value or "").strip()
    return {
        "course_code": cell(CELL_COURSE_CODE),
        "location": cell(CELL_LOCATION),
        "dates": cell(CELL_DATES),
        "venue": cell(CELL_VENUE),
        "instructor_name": cell(CELL_INSTRUCTOR) or config["instructor_name"],
    }


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def render(template: str, participant: dict, info: dict) -> str:
    return template.format(
        first_name=participant["first_name"],
        last_name=participant["last_name"],
        **info,
    )


def send_one(config: dict, to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["zoho_email"]
    msg["To"] = to_email
    msg.set_content(body)

    def _send():
        with smtplib.SMTP_SSL(config["smtp_host"], config.get("smtp_port", 465)) as smtp:
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)

    with_retry(_send)


def process_course(xlsx_path: Path, config: dict, state: dict, today: date,
                    dry_run: bool) -> int:
    """Obradi jednu tablicu tečaja. Vraća broj poslanih poruka."""
    wb = with_retry(lambda: load_workbook(xlsx_path), retry_on=(PermissionError, OSError))
    if "podaci" not in wb.sheetnames:
        return 0
    ws = wb["podaci"]

    info = course_info(ws, config)
    start = parse_start_date(info["dates"])
    if start is None:
        print(f"[!] {xlsx_path.name}: ne mogu pročitati datum tečaja "
              f"({info['dates']!r}), preskačem.")
        return 0

    days_until = (start - today).days
    if days_until < 1:
        return 0  # tečaj je danas ili je već prošao
    info["days_until"] = days_until

    participants = read_participants(ws, find_totals_row(ws))
    if not participants:
        return 0

    # Svako pravilo pokriva prozor do sljedećeg, užeg pravila: uz podsjetnike
    # na 10 i 1 dan, "10 dana prije" vrijedi za 10-2 dana, a "1 dan prije"
    # samo za točno 1 dan. Bez toga bi netko tko se prijavi 3 dana prije
    # tečaja odmah dobio i jednu i drugu poruku.
    rules = sorted(config.get("reminders", []), key=lambda r: r["days_before"], reverse=True)

    sent_count = 0
    for i, rule in enumerate(rules):
        days_before = rule["days_before"]
        donja_granica = rules[i + 1]["days_before"] if i + 1 < len(rules) else 0
        if not (donja_granica < days_until <= days_before):
            continue  # tečaj nije u prozoru ovog podsjetnika

        # Lokacija se upisuje ručno u tablicu; bez nje ne šaljemo poruku
        # koja je baš o lokaciji - radije javi da fali.
        if "{venue}" in rule["body"] and not info["venue"]:
            print(f"[!] {xlsx_path.name}: podsjetnik {days_before} dana prije traži "
                  f"lokaciju, a polje Venue (M5) je prazno - preskačem.")
            continue

        key = f"{xlsx_path.name}::{days_before}"
        already = set(state.get(key, []))
        primatelji = [p for p in participants if p["email"].lower() not in already]
        if not primatelji:
            continue

        print(f"\n{info['course_code']} / {info['location']} ({info['dates']}) - "
              f"tečaj za {days_until} dana, podsjetnik '{days_before} dana prije': "
              f"{len(primatelji)} primatelja")

        if dry_run:
            for p in primatelji:
                print(f"  - {p['first_name']} {p['last_name']} <{p['email']}>")
            print("  --- poruka ---")
            print("  Naslov:", render(rule["subject"], primatelji[0], info))
            for line in render(rule["body"], primatelji[0], info).splitlines():
                print("  " + line)
            continue

        poslano = set()
        for p in primatelji:
            try:
                send_one(config, p["email"],
                         render(rule["subject"], p, info),
                         render(rule["body"], p, info))
                poslano.add(p["email"].lower())
                sent_count += 1
                print(f"  Poslano: {p['email']}")
            except Exception as e:
                print(f"  [!] Nije poslano na {p['email']}: {e}")
            finally:
                # spremaj nakon svake poruke - ako slanje pukne na pola,
                # sljedeće pokretanje nastavlja bez dupliranja
                state[key] = sorted(already | poslano)
                save_state(state)

    return sent_count


def main():
    parser = argparse.ArgumentParser(
        description="Šalje automatske podsjetnike polaznicima prije tečaja.")
    parser.add_argument("--pregled", action="store_true",
                        help="Samo prikaži što bi poslao, bez slanja")
    args = parser.parse_args()

    config = load_config()

    if not config.get("reminders"):
        sys.exit("U config.json nema podešenih podsjetnika (polje 'reminders').")

    dry_run = args.pregled or not config.get("send_reminders")
    if dry_run and not args.pregled:
        print("send_reminders je isključen u config.json - radim samo pregled.\n")

    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    today = date.today()
    files = sorted(p for p in output_dir.glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        print(f"Nema nijedne .xlsx tablice u {output_dir}.")
        return

    state = load_state()
    total = 0
    for xlsx_path in files:
        total += process_course(xlsx_path, config, state, today, dry_run)

    print()
    if dry_run:
        print(f"Pregled gotov ({len(files)} tablica) - ništa nije poslano.")
    else:
        print(f"Gotovo. Poslano {total} podsjetnika iz {len(files)} tablica.")


if __name__ == "__main__":
    main()
