"""
Pošalji skriptu tečaja u tiskaru.

Skripte stoje u mapi 'Print' uz tablice, a svaka se zove po modulu za koji
je ('Modul 1&2.pdf', 'Modul 3.pdf'...). Tipka na stranici tečaja uzme onu
koja pripada tom tečaju, pošalje je tiskari u privitku i uz nju napiše kako
se printa i koliko kompleta treba.

Koliko kompleta - toliko koliko je polaznika u tablici u tom trenutku. Zato
se šalje kad je grupa poznata; ako se poslije netko doda, pošalje se opet i
u poruci stoji da je to ponovljena narudžba.

Adresa tiskare i tekst poruke stoje u config.json ('print_email',
'print_subject', 'print_body'); tekst se može i napisati u dokumentu
'mail printeru.docx' uz tablice, kao i svaki drugi.

Pokretanje:
    python3 posalji_na_print.py --tecaj "Modul 1&2 Split.xlsx"   # pregled
    python3 posalji_na_print.py --tecaj Split --posalji          # pošalji
"""

import argparse
import json
import mimetypes
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from openpyxl import load_workbook

import posta
import predlosci
import tablice
from predlosci import kljuc_tecaja
from send_reminders import FIRST_PARTICIPANT_ROW, course_info, find_totals_row
from zoho_to_excel import load_config, with_retry

STANJE = Path(__file__).with_name("poslani_printovi.json")
ZADANA_MAPA = "Print"

ZADANI_NASLOV = "Za print - Emmett skripta {course_code}, {location}"
ZADANO_TIJELO = """Poštovani,

u privitku je skripta za tečaj Emmett tehnike - {course_code}, {location}
({dates}).

Skripte idu na običan papir, jednostrano, u boji.
Broj kompleta: {broj_kompleta}

Lijep pozdrav,
{instructor_name}
"""


def nadji_skriptu(mapa: Path, kod: str):
    """Datoteka iz mape 'Print' koja se zove po modulu. Kvačice i velika
    slova se ne gledaju - mapu puni čovjek, pa 'Modul 1&2' i 'modul 1&2'
    moraju značiti isto."""
    if not mapa.is_dir():
        return None
    trazeni = kljuc_tecaja(kod)
    for put in sorted(mapa.iterdir()):
        if put.is_file() and not put.name.startswith("~$"):
            if kljuc_tecaja(put.stem) == trazeni:
                return put
    return None


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
                    skripta: Path) -> None:
    msg = EmailMessage()
    msg["Subject"] = naslov
    msg["From"] = config["zoho_email"]
    msg["To"] = kome
    msg.set_content(tijelo)

    tip, _ = mimetypes.guess_type(skripta.name)
    glavni, _, pod = (tip or "application/octet-stream").partition("/")
    msg.add_attachment(skripta.read_bytes(), maintype=glavni,
                       subtype=pod or "octet-stream", filename=skripta.name)

    with_retry(lambda: posta.posalji(config, msg))


def main():
    parser = argparse.ArgumentParser(
        description="Pošalji skriptu tečaja u tiskaru.")
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

    mapa_print = output_dir / config.get("print_folder", ZADANA_MAPA)
    skripta = nadji_skriptu(mapa_print, info["course_code"])
    if skripta is None:
        sys.exit(f"U {mapa_print} nema skripte za {info['course_code']!r}. "
                 f"Datoteka se mora zvati po modulu, npr. "
                 f"'{info['course_code']}.pdf'.")

    koliko = broj_polaznika(ws)
    stanje = ucitaj_stanje()
    prije = stanje.get(xlsx_path.name)

    varijable = {
        "course_code": info["course_code"],
        "location": info["location"],
        "dates": info["dates"],
        "instructor_name": info["instructor_name"],
        "broj_kompleta": str(koliko),
    }
    naslov_pred, tijelo_pred, izvor = predlosci.dohvati(
        output_dir, "mail printeru", config=config,
        kljuc_naslov="print_subject", kljuc_tijela="print_body",
        zadani_naslov=ZADANI_NASLOV, zadano_tijelo=ZADANO_TIJELO)
    naslov = predlosci.popuni(naslov_pred, varijable, izvor)
    tijelo = predlosci.popuni(tijelo_pred, varijable, izvor)

    if prije:
        tijelo += (f"\nNapomena: ovo je ponovljena narudžba za isti tečaj "
                   f"(prvi put poslano {prije.get('poslano', '?')}, tada "
                   f"{prije.get('kompleta', '?')} kompleta).\n")

    print(f"{info['course_code']} / {info['location']} ({info['dates']})")
    print(f"  skripta:  {skripta}")
    print(f"  tiskara:  {kome}")
    print(f"  kompleta: {koliko}")
    print(f"  tekst:    {izvor}")
    if prije:
        print(f"  [!] već poslano {prije.get('poslano')} "
              f"({prije.get('kompleta')} kompleta) - ovo je ponovljena narudžba")
    print("  --- poruka ---")
    print(f"  Naslov: {naslov}")
    for redak in tijelo.splitlines():
        print("  " + redak)

    if not args.posalji:
        print("\nPregled - ništa nije poslano. Za slanje dodaj --posalji")
        return

    posalji_tiskari(config, kome, naslov, tijelo, skripta)
    print(f"\nPoslano na {kome}.")

    stanje[xlsx_path.name] = {
        "poslano": date.today().isoformat(),
        "tecaj": f"{info['course_code']} / {info['location']}",
        "kompleta": koliko,
        "skripta": skripta.name,
    }
    spremi_stanje(stanje)

    try:
        posta.javi(config, f"Poslano u tiskaru: {info['course_code']}, "
                           f"{info['location']} ({koliko} kompleta)",
                   f"Skripta {skripta.name} poslana je na {kome}.\n\n"
                   f"--- poruka ---\nNaslov: {naslov}\n\n{tijelo}")
    except Exception as e:
        print(f"[!] Skripta je poslana, ali izvještaj tebi nije: {e}")


if __name__ == "__main__":
    main()
