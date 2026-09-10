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
from datetime import date, datetime, timedelta
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


def parse_course_dates(dates_text: str):
    """Vrati (prvi_dan, zadnji_dan) tečaja, ili (None, None) ako se datum ne
    može pouzdano pročitati. Za jednodnevni tečaj oba su ista."""
    if not dates_text:
        return None, None

    numbers = [int(n) for n in re.findall(r"\d+", str(dates_text))]
    if len(numbers) < 3 or numbers[-1] < 1000:
        return None, None

    year = numbers[-1]
    rest = numbers[:-1]

    if len(rest) == 2:            # d, m - jedan dan
        pocetak = (rest[0], rest[1], year)
        kraj = pocetak
    elif len(rest) == 3:          # d1, d2, m - isti mjesec
        pocetak = (rest[0], rest[2], year)
        kraj = (rest[1], rest[2], year)
    elif len(rest) == 4:          # d1, m1, d2, m2 - prelazi mjesec
        kraj = (rest[2], rest[3], year)
        # godina u zapisu pripada drugom datumu; ako tečaj prelazi Novu
        # godinu, prvi dan je godinu ranije
        pocetak = (rest[0], rest[1], year - 1 if rest[1] > rest[3] else year)
    else:
        return None, None

    try:
        prvi = date(pocetak[2], pocetak[1], pocetak[0])
        zadnji = date(kraj[2], kraj[1], kraj[0])
    except ValueError:
        return None, None

    # Kraj prije početka, ili tečaj duži od mjesec dana, znači da zapis nije
    # pročitan kako treba (npr. '30.-01.09.2026.'). Bolje reći da datum ne
    # valja nego na temelju njega nekome nešto poslati.
    if zadnji < prvi or (zadnji - prvi).days > 31:
        return None, None

    return prvi, zadnji


def parse_start_date(dates_text: str):
    """Datum PRVOG dana tečaja, ili None ako se zapis ne može pouzdano
    pročitati. Koristi istu logiku kao parse_course_dates, pa vrijede iste
    provjere (npr. odbija zapis kojem je kraj prije početka)."""
    return parse_course_dates(dates_text)[0]


MJESECI_GENITIV = [
    "siječnja", "veljače", "ožujka", "travnja", "svibnja", "lipnja",
    "srpnja", "kolovoza", "rujna", "listopada", "studenoga", "prosinca",
]


def datum_rijecima(dan: date) -> str:
    """3. listopada - oblik kakav ide u rečenicu ('Vidimo se 3. listopada')."""
    return f"{dan.day}. {MJESECI_GENITIV[dan.month - 1]}"


def iznosi_tecaja(config: dict, course_code: str) -> dict:
    """Cijena tečaja i, za tečajeve s akontacijom, koliko još preostaje.
    Vraća prazne stringove ako cijena nije podešena, da se u tekstu vidi da
    fali umjesto da se izmisli broj."""
    cijena = config.get("price_total")
    akontacija = config.get("deposit_amount")
    ima_akontaciju = course_code in config.get("deposit_course_codes", [])

    if cijena is None:
        return {"cijena": "", "akontacija": "", "preostali_iznos": ""}

    return {
        "cijena": f"{cijena:g}",
        "akontacija": f"{akontacija:g}" if akontacija is not None else "",
        "preostali_iznos": (f"{cijena - akontacija:g}"
                            if ima_akontaciju and akontacija is not None
                            else f"{cijena:g}"),
    }


DOKUMENT_NASTAVCI = [".docx", ".doc", ".pdf", ".odt"]


def _bez_dijakritika(tekst: str) -> str:
    zamjene = str.maketrans("čćžšđČĆŽŠĐ", "cczsdCCZSD")
    return tekst.translate(zamjene).lower().strip()


def nadji_dokument_lokacije(mapa: Path, location: str):
    """Nađi dokument s uputama za lokaciju - 'lokacija split.docx' za tečaj u
    Splitu. Ne pazi na velika/mala slova ni na kvačice, pa 'Lokacija Split'
    i 'lokacija split' rade jednako."""
    if not location:
        return None
    trazeno = f"lokacija {_bez_dijakritika(location)}"
    for put in sorted(mapa.iterdir()):
        if put.suffix.lower() not in DOKUMENT_NASTAVCI:
            continue
        if _bez_dijakritika(put.stem) == trazeno:
            return put
    return None


def procitaj_docx_tekst(put: Path) -> str:
    """Izvuče čisti tekst iz .docx datoteke (bez vanjskih biblioteka - .docx
    je zip s XML-om). Vrati prazan string ako to nije .docx ili se ne može
    pročitati; dokument se svejedno šalje u privitku."""
    if put.suffix.lower() != ".docx":
        return ""
    try:
        import zipfile
        with zipfile.ZipFile(put) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception:
        return ""

    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    tekst = re.sub(r"<[^>]+>", "", xml)
    tekst = (tekst.replace("&amp;", "&").replace("&lt;", "<")
                  .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
    return "\n".join(r.rstrip() for r in tekst.splitlines() if r.strip())


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


def send_one(config: dict, to_email: str, subject: str, body: str,
             privitak: Path = None) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["zoho_email"]
    msg["To"] = to_email
    msg.set_content(body)

    if privitak is not None:
        import mimetypes
        tip, _ = mimetypes.guess_type(privitak.name)
        glavni, _, pod = (tip or "application/octet-stream").partition("/")
        msg.add_attachment(privitak.read_bytes(), maintype=glavni,
                           subtype=pod or "octet-stream", filename=privitak.name)

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
    info["prvi_dan"] = datum_rijecima(start)
    # Ostatak kotizacije se plaća tjedan dana prije početka
    rok = start - timedelta(days=config.get("payment_due_days_before", 7))
    info["rok_uplate"] = rok.strftime("%d.%m.%Y.")
    info.update(iznosi_tecaja(config, info["course_code"]))

    # Dio o uplati se razlikuje: kod tečaja s akontacijom preostaje razlika,
    # kod ostalih se plaća puni iznos.
    if info["course_code"] in config.get("deposit_course_codes", []):
        blok = config.get("reminder_deposit_block", "")
    else:
        blok = config.get("reminder_no_deposit_block", "")
    info["blok_uplate"] = blok.format(**info) if blok else ""

    participants = read_participants(ws, find_totals_row(ws))
    if not participants:
        return 0

    # Upute za lokaciju stoje u zasebnom dokumentu uz tablice, imenovanom po
    # gradu ('lokacija split.docx'). Šalje se u privitku, a tekst iz njega je
    # dostupan i kao {lokacija_tekst} ako ga želiš u samoj poruci.
    dokument = nadji_dokument_lokacije(xlsx_path.parent, info["location"])
    info["lokacija_tekst"] = procitaj_docx_tekst(dokument) if dokument else ""

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

        # Bez dokumenta s uputama nema smisla slati poruku koja na njega
        # upućuje - radije javi da fali, pa ga dodaš i poruka ode sama.
        if rule.get("attach_location") and dokument is None:
            print(f"[!] {xlsx_path.name}: podsjetnik {days_before} dana prije treba "
                  f"dokument s lokacijom - nedostaje 'lokacija {info['location']}.docx' "
                  f"u {xlsx_path.parent} - preskačem.")
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
                         render(rule["body"], p, info),
                         privitak=dokument if rule.get("attach_location") else None)
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


def show_overview(files: list, config: dict, state: dict, today: date) -> None:
    """Ispiše što skripta vidi u svakoj tablici i zašto (ne)šalje podsjetnik.
    Korisno kad --pregled ništa ne pokaže, pa nije jasno je li problem u
    datumu, praznoj dvorani ili je jednostavno još prerano."""
    rules = sorted(config.get("reminders", []), key=lambda r: r["days_before"], reverse=True)

    for xlsx_path in files:
        wb = with_retry(lambda: load_workbook(xlsx_path), retry_on=(PermissionError, OSError))
        if "podaci" not in wb.sheetnames:
            print(f"{xlsx_path.name}: nema list 'podaci', preskačem.")
            continue
        ws = wb["podaci"]
        info = course_info(ws, config)
        broj = len(read_participants(ws, find_totals_row(ws)))
        start = parse_start_date(info["dates"])

        print(f"\n{xlsx_path.name}")
        print(f"  Tečaj:     {info['course_code']} / {info['location']}")
        print(f"  Datum:     {info['dates'] or '(prazno)'}", end="")

        if start is None:
            print("  -> NE MOGU PROČITATI, podsjetnici se ne šalju")
            continue
        days_until = (start - today).days
        print(f"  -> počinje {start.strftime('%d.%m.%Y')} ({days_until} dana)")
        print(f"  Polaznika: {broj}")
        print(f"  Dvorana:   {info['venue'] or 'PRAZNO (polje M5)'}")

        if days_until < 1:
            print("  Status:    tečaj je prošao ili je danas - ništa se ne šalje")
            continue
        if broj == 0:
            print("  Status:    nema upisanih polaznika - nema kome slati")
            continue

        for i, rule in enumerate(rules):
            dana = rule["days_before"]
            donja = rules[i + 1]["days_before"] if i + 1 < len(rules) else 0
            poslano = len(state.get(f"{xlsx_path.name}::{dana}", []))
            if poslano:
                stanje = f"već poslano ({poslano})"
            elif days_until > dana:
                stanje = f"još nije vrijeme (kreće na {dana} dana)"
            elif days_until <= donja:
                stanje = "prozor je prošao"
            elif "{venue}" in rule["body"] and not info["venue"]:
                stanje = "SPREMNO, ali čeka da upišeš dvoranu u M5"
            else:
                stanje = f"ŠALJE SE ({broj} polaznika)"
            print(f"  {dana:>2} dana prije: {stanje}")


def main():
    parser = argparse.ArgumentParser(
        description="Šalje automatske podsjetnike polaznicima prije tečaja.")
    parser.add_argument("--pregled", action="store_true",
                        help="Samo prikaži što bi poslao, bez slanja")
    parser.add_argument("--popis", action="store_true",
                        help="Ispiši stanje svake tablice (datum, polaznici, dvorana)")
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
    files = sorted(p for p in output_dir.glob("*.xlsx") if not p.name.startswith("~$")
                      and p.name != "template_admin_sheet.xlsx")
    if not files:
        print(f"Nema nijedne .xlsx tablice u {output_dir}.")
        return

    state = load_state()

    if args.popis:
        show_overview(files, config, state, today)
        print(f"\nUkupno {len(files)} tablica.")
        return

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
