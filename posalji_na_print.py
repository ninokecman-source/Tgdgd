"""
Pošalji materijale tečaja u tiskaru.

Materijali stoje u mapi 'Print' uz tablice, a svaki se zove po onome što
jest ('Modul 1&2.pdf', 'Disclaimer.pdf', 'Zdravstveni obrazac.pdf'...).
Tipka na stranici tečaja složi narudžbu za taj tečaj: priloži datoteke i uz
svaku napiše koliko kompleta i na kakav papir.

Što ide uz koji modul stoji u config.json, pod 'print_items':

    "print_items": {
      "Modul 1&2": [
        {"datoteka": "Modul 1&2"},
        {"datoteka": "Disclaimer"},
        {"datoteka": "Zdravstveni obrazac", "koliko": "pola"}
      ],
      "Ponavljanje M6 i Praktičarski dan": [
        {"datoteka": "Praktičarski ispit"},
        {"certifikati": true, "papir": "tvrđi papir"}
      ]
    }

  datoteka      naziv datoteke u mapi 'Print', bez nastavka
  certifikati   umjesto datoteke: gotove potvrdnice tog tečaja, svaka u
                jednom primjerku
  koliko        'polaznici' (zadano), 'pola' (pola toliko, zaokruženo gore)
                ili broj
  papir         ako se razlikuje od zadanog

Za modul koji nije naveden šalje se jedna datoteka, nazvana po njemu.

Narudžba ne ide nepotpuna: ako koja datoteka nedostaje, skripta to javi i
ne šalje ništa.

Pokretanje:
    python3 posalji_na_print.py --tecaj "Modul 1&2 Split.xlsx"   # pregled
    python3 posalji_na_print.py --tecaj Split --posalji          # pošalji
"""

import argparse
import json
import math
import mimetypes
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from openpyxl import load_workbook

import posta
import predlosci
import tablice
from napravi_certifikate import ime_mape
from predlosci import kljuc_tecaja
from send_reminders import (
    FIRST_PARTICIPANT_ROW,
    course_info,
    find_totals_row,
    parse_course_dates,
)
from zoho_to_excel import load_config, with_retry

STANJE = Path(__file__).with_name("poslani_printovi.json")
ZADANA_MAPA = "Print"
ZADANI_PAPIR = "običan papir"
# Zoho odbija poruke iznad 25 MB; ispod te granice se staje s porukom koja
# se da pročitati, umjesto da slanje padne na pola.
NAJVECI_PRILOG = 20 * 1024 * 1024

ZADANI_NASLOV = "Za print - Emmett {course_code}, {location}"
ZADANO_TIJELO = """Poštovani,

u privitku je materijal za tečaj Emmett tehnike - {course_code}, {location}
({dates}).

{stavke}
Sve ide jednostrano, u boji.

Lijep pozdrav,
{instructor_name}
"""


def stavke_za(config: dict, kod: str) -> list:
    """Što sve ide u tiskaru za ovaj modul."""
    popis = config.get("print_items") or {}
    for zapis, stavke in popis.items():
        if kljuc_tecaja(zapis) == kljuc_tecaja(kod) and stavke:
            return stavke
    return [{"datoteka": kod}]


def kolicina(zapis, polaznika: int) -> int:
    """'polaznici' -> koliko ih je, 'pola' -> pola toliko (zaokruženo gore),
    broj -> taj broj."""
    if zapis in (None, "", "polaznici"):
        return polaznika
    if zapis == "pola":
        return math.ceil(polaznika / 2)
    try:
        return max(0, int(zapis))
    except (TypeError, ValueError):
        raise ValueError(f"ne razumijem koliko: {zapis!r}")


def nadji_datoteku(mapa: Path, naziv: str):
    """Datoteka iz mape 'Print' po nazivu, bez obzira na nastavak. Kvačice i
    velika slova se ne gledaju - mapu puni čovjek."""
    if not mapa.is_dir():
        return None
    trazeni = kljuc_tecaja(naziv)
    for put in sorted(mapa.iterdir()):
        if put.is_file() and not put.name.startswith("~$"):
            if kljuc_tecaja(put.stem) == trazeni:
                return put
    return None


def mapa_certifikata(xlsx_path: Path, info: dict):
    _, kraj = parse_course_dates(info["dates"])
    if kraj is None:
        return None
    return xlsx_path.parent / "Certifikati" / ime_mape(info, kraj)


def slozi_narudzbu(config: dict, xlsx_path: Path, info: dict,
                   polaznika: int) -> tuple:
    """([stavke], [što nedostaje]). Stavka je
    {naziv, datoteke, kolicina, papir, po_datoteci}."""
    mapa_print = Path(config["output_dir"]) / config.get("print_folder", ZADANA_MAPA)
    zadani_papir = config.get("print_paper", ZADANI_PAPIR)
    narudzba, fali = [], []

    for zapis in stavke_za(config, info["course_code"]):
        papir = zapis.get("papir") or zadani_papir

        if zapis.get("certifikati"):
            mapa = mapa_certifikata(xlsx_path, info)
            pdfovi = sorted(mapa.glob("*.pdf")) if mapa and mapa.is_dir() else []
            if not pdfovi:
                fali.append(f"potvrdnice tog tečaja (mapa {mapa}) - "
                            f"napravi ih pa ponovi")
                continue
            narudzba.append({
                "naziv": "Potvrdnice",
                "datoteke": pdfovi,
                "kolicina": 1,
                "papir": papir,
                "po_datoteci": True,
            })
            continue

        naziv = zapis.get("datoteka") or info["course_code"]
        put = nadji_datoteku(mapa_print, naziv)
        if put is None:
            fali.append(f"'{naziv}' u mapi {mapa_print}")
            continue
        narudzba.append({
            "naziv": put.name,
            "datoteke": [put],
            "kolicina": kolicina(zapis.get("koliko"), polaznika),
            "papir": papir,
            "po_datoteci": False,
        })

    return narudzba, fali


def broj_rijecima(koliko: int, jedan: str, dva: str, pet: str) -> str:
    """'1 komplet', '3 kompleta', '7 kompleta' - hrvatski broji na tri
    načina, a narudžba se čita naglas u tiskari."""
    zadnje, zadnja_dva = koliko % 10, koliko % 100
    if zadnja_dva in range(11, 15):
        oblik = pet
    elif zadnje == 1:
        oblik = jedan
    elif zadnje in (2, 3, 4):
        oblik = dva
    else:
        oblik = pet
    return f"{koliko} {oblik}"


def opis_stavki(narudzba: list) -> str:
    redci = []
    for s in narudzba:
        if s["po_datoteci"]:
            koliko = broj_rijecima(len(s["datoteke"]), "datoteka", "datoteke",
                                   "datoteka")
            redci.append(f"- {s['naziv']}: {koliko}, svaka u jednom "
                         f"primjerku, {s['papir']}")
        else:
            koliko = broj_rijecima(s["kolicina"], "komplet", "kompleta",
                                   "kompleta")
            redci.append(f"- {s['naziv']}: {koliko}, {s['papir']}")
    return "\n".join(redci) + "\n"


def ucitaj_stanje() -> dict:
    if not STANJE.exists():
        return {}
    try:
        with open(STANJE, encoding="utf-8") as f:
            podaci = json.load(f)
        return podaci if isinstance(podaci, dict) else {}
    except (ValueError, OSError):
        return {}


def spremi_stanje(stanje: dict) -> None:
    with open(STANJE, "w", encoding="utf-8") as f:
        json.dump(stanje, f, ensure_ascii=False, indent=2, sort_keys=True)


def broj_polaznika(ws) -> int:
    koliko = 0
    for row in range(FIRST_PARTICIPANT_ROW, find_totals_row(ws)):
        if ws.cell(row=row, column=2).value or ws.cell(row=row, column=3).value:
            koliko += 1
    return koliko


def posalji_tiskari(config: dict, kome: str, naslov: str, tijelo: str,
                    narudzba: list) -> None:
    msg = EmailMessage()
    msg["Subject"] = naslov
    msg["From"] = config["zoho_email"]
    msg["To"] = kome
    msg.set_content(tijelo)

    for stavka in narudzba:
        for put in stavka["datoteke"]:
            tip, _ = mimetypes.guess_type(put.name)
            glavni, _, pod = (tip or "application/octet-stream").partition("/")
            msg.add_attachment(put.read_bytes(), maintype=glavni,
                               subtype=pod or "octet-stream", filename=put.name)

    with_retry(lambda: posta.posalji(config, msg))


def main():
    parser = argparse.ArgumentParser(
        description="Pošalji materijale tečaja u tiskaru.")
    parser.add_argument("--tecaj", required=True, metavar="DIO NAZIVA")
    parser.add_argument("--posalji", action="store_true",
                        help="Stvarno pošalji; bez ovoga je samo pregled")
    args = parser.parse_args()

    config = load_config()
    kome = (config.get("print_email") or "").strip()
    if not kome:
        sys.exit('Nema adrese tiskare - upiši je u config.json kao "print_email".')

    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    trazeno = predlosci.bez_dijakritika(args.tecaj)
    datoteke = [p for p in tablice.nadji(output_dir)
                if trazeno in predlosci.bez_dijakritika(p.name)]
    if not datoteke:
        sys.exit(f"Nijedna tablica u nazivu nema {args.tecaj!r}.")
    if len(datoteke) > 1:
        sys.exit("Na ovo ime pristaje više tablica: "
                 + ", ".join(p.name for p in datoteke))
    xlsx_path = datoteke[0]

    wb = with_retry(lambda: load_workbook(xlsx_path),
                    retry_on=(PermissionError, OSError))
    if "podaci" not in wb.sheetnames:
        sys.exit(f"{xlsx_path.name} nema list 'podaci'.")
    ws = wb["podaci"]
    info = course_info(ws, config)
    polaznika = broj_polaznika(ws)

    try:
        narudzba, fali = slozi_narudzbu(config, xlsx_path, info, polaznika)
    except ValueError as e:
        sys.exit(f"Postavka 'print_items' za {info['course_code']!r}: {e}")

    print(f"{info['course_code']} / {info['location']} ({info['dates']})")
    print(f"  polaznika: {polaznika}")
    print(f"  tiskara:   {kome}")
    for stavka in narudzba:
        koliko = (f"{len(stavka['datoteke'])} datoteka, svaka jednom"
                  if stavka["po_datoteci"] else f"{stavka['kolicina']} kompleta")
        print(f"    {stavka['naziv']:<34} {koliko}, {stavka['papir']}")
    for sto in fali:
        print(f"  [!] nedostaje {sto}")

    if fali:
        sys.exit("\nNarudžba nije potpuna, pa nije ni poslana. "
                 "Dopuni pa pokreni ponovno.")
    if not narudzba:
        sys.exit(f"\nZa {info['course_code']!r} nema što slati u tiskaru.")

    ukupno = sum(p.stat().st_size for s in narudzba for p in s["datoteke"])
    if ukupno > NAJVECI_PRILOG:
        sys.exit(f"\nPrilozi su {ukupno / 1024 / 1024:.1f} MB, previše za jedan "
                 f"mail. Pošalji potvrdnice odvojeno ili ih smanji.")

    stanje = ucitaj_stanje()
    prije = stanje.get(xlsx_path.name)

    varijable = {
        "course_code": info["course_code"],
        "location": info["location"],
        "dates": info["dates"],
        "instructor_name": info["instructor_name"],
        "broj_polaznika": str(polaznika),
        "stavke": opis_stavki(narudzba),
    }
    naslov_pred, tijelo_pred, izvor = predlosci.dohvati(
        output_dir, "mail printeru", config=config,
        kljuc_naslov="print_subject", kljuc_tijela="print_body",
        zadani_naslov=ZADANI_NASLOV, zadano_tijelo=ZADANO_TIJELO)
    naslov = predlosci.popuni(naslov_pred, varijable, izvor)
    tijelo = predlosci.popuni(tijelo_pred, varijable, izvor)

    if prije:
        tijelo += (f"\nNapomena: ovo je ponovljena narudžba za isti tečaj "
                   f"(prvi put poslano {prije.get('poslano', '?')}, tada za "
                   f"{prije.get('polaznika', '?')} polaznika).\n")
        print(f"  [!] već poslano {prije.get('poslano')} - "
              f"ovo je ponovljena narudžba")

    print(f"  tekst:     {izvor}")
    print("  --- poruka ---")
    print(f"  Naslov: {naslov}")
    for redak in tijelo.splitlines():
        print("  " + redak)

    if not args.posalji:
        print("\nPregled - ništa nije poslano. Za slanje dodaj --posalji")
        return

    posalji_tiskari(config, kome, naslov, tijelo, narudzba)
    print(f"\nPoslano na {kome} ({ukupno / 1024 / 1024:.1f} MB priloga).")

    stanje[xlsx_path.name] = {
        "poslano": date.today().isoformat(),
        "tecaj": f"{info['course_code']} / {info['location']}",
        "polaznika": polaznika,
        "stavke": [s["naziv"] for s in narudzba],
    }
    spremi_stanje(stanje)

    try:
        posta.javi(config, f"Poslano u tiskaru: {info['course_code']}, "
                           f"{info['location']}",
                   f"Narudžba je poslana na {kome}.\n\n"
                   f"--- poruka ---\nNaslov: {naslov}\n\n{tijelo}")
    except Exception as e:
        print(f"[!] Narudžba je poslana, ali izvještaj tebi nije: {e}")


if __name__ == "__main__":
    main()
