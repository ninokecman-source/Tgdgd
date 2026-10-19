"""
Što je trebalo biti poslano, a nije.

Ne šalje ništa i ništa ne mijenja - samo uspoređuje pravila s onim što je
zabilježeno kao poslano, i čita logove.

Razlog zašto ovo uopće treba: nakon prekida u slanju (zatvoren SMTP port,
pala mreža) neke se poruke same poprave, a neke su zauvijek propuštene -
ovisi o tome ima li posao još prilika pokušati.

    SAME SE POPRAVE                      ZAUVIJEK PROPUŠTENO
    podsjetnik '10 dana prije'           potvrda prijave
      (pokušava 10. do 2. dana)            (mail je već označen obrađenim)
    tablica centrali                     podsjetnik '1 dan prije'
      (uvjet ostaje istinit)               (prozor traje jedan dan)
    potvrdnice (ručno)                   potvrda uplate iz banke
    obavijest o nepovezanoj uplati         (greška se uhvati i ispiše)
    provjera logova

Pokretanje:
    python3 provjeri_slanja.py
    python3 provjeri_slanja.py --od 2026-10-14     # samo od selidbe nadalje
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

import tablice
from provjeri_logove import DEFAULT_LOGS
from send_reminders import COL_EMAIL, course_info, parse_start_date
from zoho_to_excel import (
    FIRST_PARTICIPANT_ROW,
    find_totals_row,
    load_config,
    with_retry,
)

# Retci koji znače da poruka nije otišla.
NEUSPJEH = [
    re.compile(r"Nije poslano na", re.IGNORECASE),
    re.compile(r"nije poslan[ao]?", re.IGNORECASE),
    re.compile(r"Greška pri slanju", re.IGNORECASE),
]
ZAGLAVLJE = re.compile(r"^=== (\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} (.+?)\s*===$")


def citaj_json(put: Path):
    if not put.exists():
        return {}
    try:
        with open(put, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def neuspjela_slanja(config: dict, od: date) -> list:
    """[(datum, posao, redak)] iz svih praćenih logova."""
    nalazi = []
    for naziv, put_tekst in config.get("watch_logs", DEFAULT_LOGS).items():
        put = Path(put_tekst).expanduser()
        if not put.exists():
            continue
        with open(put, "rb") as f:
            tekst = f.read().decode("utf-8", errors="replace")
        kada, posao = "", naziv
        for redak in tekst.splitlines():
            zag = ZAGLAVLJE.match(redak.strip())
            if zag:
                kada, posao = zag.group(1), zag.group(2)
                continue
            if kada and kada < od.isoformat():
                continue
            if any(u.search(redak) for u in NEUSPJEH):
                nalazi.append((kada, posao, redak.strip()))
    return nalazi


def provjeri_podsjetnike(datoteke, config, danas):
    """[(tablica, dana_prije, stanje, koliko)] - po jednom pravilu i tečaju."""
    pravila = sorted(config.get("reminders", []),
                     key=lambda r: r["days_before"], reverse=True)
    stanje = citaj_json(Path(__file__).with_name("sent_reminders.json"))
    nalazi = []

    for put in datoteke:
        wb = with_retry(lambda: load_workbook(put), retry_on=(PermissionError, OSError))
        if "podaci" not in wb.sheetnames:
            continue
        ws = wb["podaci"]
        info = course_info(ws, config)
        pocetak = parse_start_date(info["dates"])
        if pocetak is None:
            continue
        dana_do = (pocetak - danas).days

        adrese = {str(ws.cell(row=r, column=COL_EMAIL).value or "").strip().lower()
                  for r in range(FIRST_PARTICIPANT_ROW, find_totals_row(ws))}
        adrese.discard("")
        if not adrese:
            continue

        for i, pravilo in enumerate(pravila):
            dana_prije = pravilo["days_before"]
            donja = pravila[i + 1]["days_before"] if i + 1 < len(pravila) else 0
            poslano = {a.lower() for a in
                       stanje.get(f"{put.name}::{dana_prije}", [])}
            fali = adrese - poslano
            if not fali:
                continue
            if dana_do > dana_prije:
                polozaj = "jos nije na redu"
            elif dana_do > donja:
                polozaj = "u prozoru - poslat ce se sam"
            else:
                polozaj = "PROPUSTENO"
            nalazi.append((f"{info['course_code']} / {info['location']}",
                           put.name, dana_prije, polozaj, len(fali), dana_do))
    return nalazi


def kraj_tecaja(put: Path, config: dict):
    """Zadnji dan tečaja iz tablice, ili None ako se ne može pročitati."""
    from send_reminders import parse_course_dates
    try:
        wb = with_retry(lambda: load_workbook(put), retry_on=(PermissionError, OSError))
        if "podaci" not in wb.sheetnames:
            return None
        return parse_course_dates(course_info(wb["podaci"], config)["dates"])[1]
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Provjeri je li koja poruka trebala otići, a nije.")
    parser.add_argument("--od", metavar="GGGG-MM-DD",
                        help="Gledaj logove samo od tog datuma")
    args = parser.parse_args()

    od = date.min
    if args.od:
        try:
            od = date.fromisoformat(args.od)
        except ValueError:
            sys.exit(f"Neispravan datum: {args.od!r}")

    config = load_config()
    danas = date.today()
    output_dir = Path(config["output_dir"])
    datoteke = tablice.nadji(output_dir, javi=lambda _: None)

    print("POSTAVKE SLANJA")
    for kljuc, opis, popravlja in [
            ("send_replies", "potvrda prijave", "NE - mail ostaje obradjen"),
            ("send_reminders", "podsjetnici", "djelomicno - vidi nize"),
            ("send_course_report", "tablica centrali", "da"),
    ]:
        print(f"  {opis:22} {str(config.get(kljuc, False)):6} "
              f"ponavlja nakon greske: {popravlja}")
    banka = citaj_json(Path(__file__).with_name("bank_solo") / "config.json")
    print(f"  {'potvrda uplate':22} {str(banka.get('send_payment_confirmation', False)):6} "
          f"ponavlja nakon greske: NE - greska se samo ispise")

    print("\nNEUSPJELA SLANJA U LOGOVIMA"
          + (f" (od {od})" if od != date.min else ""))
    nalazi = neuspjela_slanja(config, od)
    if not nalazi:
        print("  Nijedno. Nijedna poruka nije pala pri slanju.")
    for kada, posao, redak in nalazi[-40:]:
        print(f"  {kada}  {posao:24} {redak[:110]}")

    print("\nPODSJETNICI")
    podsjetnici = provjeri_podsjetnike(datoteke, config, danas)
    if not podsjetnici:
        print("  Svi su podsjetnici poslani svima, ili ih nema za slati.")
    for tecaj, datoteka, dana_prije, polozaj, koliko, dana_do in podsjetnici:
        oznaka = "[!]" if polozaj == "PROPUSTENO" else "   "
        print(f"  {oznaka} {tecaj:30} '{dana_prije} "
              f"{'dan' if dana_prije == 1 else 'dana'} prije': "
              f"{koliko} bez poruke - {polozaj} (tecaj za {dana_do} dana)")

    print("\nTABLICA CENTRALI")
    poslane = citaj_json(Path(__file__).with_name("sent_reports.json"))
    dana_nakon = config.get("course_report_days_after", 1)
    nasli = False
    for put in datoteke:
        if put.name in poslane and poslane[put.name].get("poslano"):
            continue
        kraj = kraj_tecaja(put, config)
        if kraj is None:
            continue
        proslo = (danas - kraj).days
        nasli = True
        if proslo < dana_nakon:
            print(f"      {put.name} - tecaj jos nije prosao")
        elif put.name in poslane and poslane[put.name].get("nedostaje"):
            fali = ", ".join(poslane[put.name]["nedostaje"])
            print(f"  [!] {put.name} - prosao prije {proslo} dana, ne salje se "
                  f"jer u tablici fali: {fali}")
        else:
            print(f"  [!] {put.name} - prosao prije {proslo} dana, NIJE poslana "
                  f"(trebala je prije {proslo - dana_nakon} dana)")
    if not nasli:
        print("  Sve su poslane.")

    print("\nPOTVRDNICE")
    napravljene = citaj_json(Path(__file__).with_name("napravljeni_certifikati.json"))
    poslane_p = citaj_json(Path(__file__).with_name("poslani_certifikati.json"))
    nasli = False
    for naziv, podaci in napravljene.items():
        koliko = len(podaci.get("polaznici", []))
        otislo = len(poslane_p.get(naziv, {}).get("poslano", []))
        if otislo < koliko:
            nasli = True
            print(f"      {podaci.get('tecaj', naziv)}: napravljeno {koliko}, "
                  f"poslano {otislo} - salju se na tvoju naredbu")
    if not nasli:
        print("  Nema napravljenih potvrdnica koje cekaju slanje.")

    print("\nSto ovo NE moze provjeriti: potvrde prijave i potvrde uplate.")
    print("Za njih ne postoji popis 'kome je poslano', pa se vide samo u")
    print("logovima gore - ako ih ondje nema, nijedna nije pala.")


if __name__ == "__main__":
    main()
