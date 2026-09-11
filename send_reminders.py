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

Tekst svakog podsjetnika stoji u svom dokumentu uz Excel tablice -
'podsjetnik 10 dana.docx' i 'podsjetnik 1 dan.docx' - isto kao upute o
lokaciji ('lokacija split.docx'). Uređuje se u Wordu, bez diranja configa;
detalji su u predlosci.py. U config.json ostaju samo rokovi (polje
"reminders": days_before), a slanje se uključuje s "send_reminders": true.

Naziv dvorane se NE čita iz tablice - uzima se iz dokumenta o lokaciji
(redak 'Dvorana: ...', ili prvi redak dokumenta).

Skripta pamti kome je koji podsjetnik poslala (sent_reminders.json), pa
nitko ne dobiva istu poruku dvaput, koliko god puta se skripta pokrenula.
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

import predlosci
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

# Zaglavlje tablice: kod tečaja, mjesto, datumi, instruktor.
# Dvorana (M5) se namjerno NE čita - naziv dvorane dolazi iz dokumenta o
# lokaciji, zajedno s ostalim uputama, pa se upisuje na jednom mjestu.
CELL_COURSE_CODE = "C4"
CELL_LOCATION = "C5"
CELL_DATES = "C6"
CELL_INSTRUCTOR = "M4"


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


# Čitanje dokumenata (lokacija, tekstovi poruka) živi u predlosci.py - ovdje
# su samo imena pod kojima ga ostatak skripte zove.
DOKUMENT_NASTAVCI = predlosci.NASTAVCI
procitaj_tekst_dokumenta = predlosci.procitaj_tekst


def nadji_dokument_lokacije(mapa: Path, location: str):
    """Dokument s uputama za lokaciju - 'lokacija split.docx' za tečaj u
    Splitu."""
    return predlosci.dokument_lokacije(mapa, location)


def nazivi_podsjetnika(rule: dict) -> list:
    """Pod kojim se nazivom traži dokument s tekstom ovog podsjetnika.
    Može se zadati izrijekom ("predlozak" u pravilu), inače se izvodi iz
    roka: 10 -> 'podsjetnik 10 dana', 1 -> 'podsjetnik 1 dan'."""
    if rule.get("predlozak"):
        return [rule["predlozak"]]
    dana = rule["days_before"]
    jedinica = "dan" if dana == 1 else "dana"
    return [f"podsjetnik {dana} {jedinica}",
            f"podsjetnik {dana} {jedinica} prije"]


ZADANI_NASLOV = "Emmett tehnika - {course_code}, {location} ({dates})"


def blok_uplate(mapa: Path, config: dict, course_code: str):
    """(naslov, tijelo, izvor) za odlomak o uplati koji se uvrštava u
    podsjetnik kao {blok_uplate}. Tečajevi s akontacijom dobivaju tekst o
    ostatku kotizacije, ostali o punom iznosu."""
    if course_code in config.get("deposit_course_codes", []):
        nazivi, kljuc = ["blok uplate akontacija"], "reminder_deposit_block"
    else:
        nazivi, kljuc = ["blok uplate puni iznos"], "reminder_no_deposit_block"
    return predlosci.dohvati(mapa, nazivi, config=config, kljuc_tijela=kljuc)



def tekst_podsjetnika(mapa: Path, rule: dict, config: dict):
    """(naslov, tijelo, izvor) za jedan podsjetnik: dokument uz tablice ima
    prednost, a ako ga nema, uzima se tekst upisan u config.json."""
    return predlosci.dohvati(
        mapa, nazivi_podsjetnika(rule),
        config={"subject": rule.get("subject"), "body": rule.get("body")},
        kljuc_naslov="subject", kljuc_tijela="body",
        zadani_naslov=config.get("reminder_subject") or ZADANI_NASLOV,
    )


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
        "venue": "",   # popunjava se iz dokumenta o lokaciji, ne iz tablice
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
    info["prvi_dan"] = datum_rijecima(start)
    # Ostatak kotizacije se plaća tjedan dana prije početka
    rok = start - timedelta(days=config.get("payment_due_days_before", 7))
    info["rok_uplate"] = rok.strftime("%d.%m.%Y.")
    info.update(iznosi_tecaja(config, info["course_code"]))

    mapa = xlsx_path.parent

    # Dio o uplati se razlikuje: kod tečaja s akontacijom preostaje razlika,
    # kod ostalih se plaća puni iznos. Tekst stoji u svom dokumentu
    # ('blok uplate akontacija' / 'blok uplate puni iznos'), kao i sve ostalo.
    _, blok, _ = blok_uplate(mapa, config, info["course_code"])
    # Blok uvijek zavrsava praznim retkom, pa se ne slijepi s tekstom
    # koji u podsjetniku dolazi iza njega.
    info["blok_uplate"] = (blok.format(**info).rstrip("\n") + "\n\n") if blok else ""

    participants = read_participants(ws, find_totals_row(ws))
    if not participants:
        return 0

    # Upute za lokaciju stoje u zasebnom dokumentu uz tablice, imenovanom po
    # gradu ('lokacija split.docx'). Tekst iz njega se ugrađuje u poruku kao
    # {lokacija_tekst} - dokument se ne šalje u privitku. Iz istog dokumenta
    # dolazi i naziv dvorane ({venue}).
    dokument = nadji_dokument_lokacije(mapa, info["location"])
    tekst_lokacije = procitaj_tekst_dokumenta(dokument) if dokument else ""
    info["venue"], info["lokacija_tekst"] = predlosci.rastavi_lokaciju(tekst_lokacije)

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

        naslov_predloska, tijelo, izvor = tekst_podsjetnika(mapa, rule, config)
        if not tijelo:
            print(f"[!] {xlsx_path.name}: za podsjetnik {days_before} dana prije nema "
                  f"teksta - napravi dokument '{nazivi_podsjetnika(rule)[0]}.docx' u "
                  f"{mapa} - preskačem.")
            continue

        # Poruka koja uključuje upute za lokaciju (ili naziv dvorane) nema
        # smisla bez njih - radije javi što fali, pa se pošalje sama kad to
        # središ. Oboje dolazi iz istog dokumenta.
        if ("{lokacija_tekst}" in tijelo or "{venue}" in tijelo) and not info["lokacija_tekst"]:
            if dokument is None:
                print(f"[!] {xlsx_path.name}: podsjetnik {days_before} dana prije treba "
                      f"upute za lokaciju - nedostaje 'lokacija {info['location']}.docx' "
                      f"u {mapa} - preskačem.")
            else:
                print(f"[!] {xlsx_path.name}: iz dokumenta {dokument.name} ne mogu "
                      f"pročitati tekst - spremi ga kao .docx - preskačem.")
            continue

        if "{venue}" in tijelo and not info["venue"]:
            print(f"[!] {xlsx_path.name}: podsjetnik {days_before} dana prije traži naziv "
                  f"dvorane, a u dokumentu {dokument.name} nema retka 'Dvorana: ...' "
                  f"- preskačem.")
            continue

        key = f"{xlsx_path.name}::{days_before}"
        already = set(state.get(key, []))
        primatelji = [p for p in participants if p["email"].lower() not in already]
        if not primatelji:
            continue

        print(f"\n{info['course_code']} / {info['location']} ({info['dates']}) - "
              f"tečaj za {days_until} dana, podsjetnik '{days_before} dana prije': "
              f"{len(primatelji)} primatelja (tekst: {izvor})")

        if dry_run:
            for p in primatelji:
                print(f"  - {p['first_name']} {p['last_name']} <{p['email']}>")
            print("  --- poruka ---")
            print("  Naslov:", render(naslov_predloska, primatelji[0], info))
            for line in render(tijelo, primatelji[0], info).splitlines():
                print("  " + line)
            continue

        poslano = set()
        for p in primatelji:
            try:
                send_one(config, p["email"],
                         render(naslov_predloska, p, info),
                         render(tijelo, p, info))
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

        mapa = xlsx_path.parent
        dokument = nadji_dokument_lokacije(mapa, info["location"])
        tekst_lokacije = procitaj_tekst_dokumenta(dokument) if dokument else ""
        info["venue"] = predlosci.dvorana_iz_teksta(tekst_lokacije)
        info["lokacija_tekst"] = tekst_lokacije

        if dokument is None:
            print(f"  Upute:     NEMA dokumenta 'lokacija {info['location']}.docx'")
        elif not tekst_lokacije:
            print(f"  Upute:     {dokument.name} - NE MOGU pročitati tekst (spremi kao .docx)")
        else:
            print(f"  Upute:     {dokument.name} "
                  f"({len(tekst_lokacije.splitlines())} redaka teksta)")
        print(f"  Dvorana:   {info['venue'] or 'nema je u dokumentu o lokaciji'}")

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
            else:
                _, tijelo, izvor = tekst_podsjetnika(mapa, rule, config)
                if not tijelo:
                    stanje = (f"NEMA TEKSTA - napravi "
                              f"'{nazivi_podsjetnika(rule)[0]}.docx'")
                elif ("{lokacija_tekst}" in tijelo or "{venue}" in tijelo) \
                        and not tekst_lokacije:
                    stanje = "SPREMNO, ali čeka dokument o lokaciji"
                elif "{venue}" in tijelo and not info["venue"]:
                    stanje = ("SPREMNO, ali u dokumentu o lokaciji nema "
                              "retka 'Dvorana: ...'")
                else:
                    stanje = f"ŠALJE SE ({broj} polaznika, tekst: {izvor})"
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

    # Rokovi se mogu podesiti u configu; ako ih nema, vrijede uobičajena dva
    # (10 dana i 1 dan prije), a tekst im dolazi iz dokumenata uz tablice.
    if not config.get("reminders"):
        config["reminders"] = [{"days_before": 10}, {"days_before": 1}]
        print("U config.json nema polja 'reminders' - koristim rokove 10 i 1 dan "
              "prije, a tekst čitam iz dokumenata uz tablice.\n")

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
