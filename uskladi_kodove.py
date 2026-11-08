"""
Uskladi kodove tečajeva: tablice i config.json govore isto.

Kod tečaja iz ćelije C4 nije samo naljepnica - po njemu se traži koja
potvrdnica ide, prepoznaje li se prijava iz maila, kako se zove opis na Solo
ponudi i što ide u tiskaru. Tablice ispunjava čovjek, pa jedno slovo više ili
manje tiho prekine sve to: skripta javi "za tečaj ... nema potvrdnice", a
prijave za taj tečaj prestanu ulaziti.

Ova skripta to poravna, i to u dva koraka:

1. Pospremi ćelije C4, C5 i C6 u svim tablicama - samo razmaci, nikad slova.
   Razmak na kraju C4 ne kvari prepoznavanje (kljuc_tecaja ga sabija), ali
   ulazi u naslov maila polazniku kao dvostruki razmak.

2. Nađi mjesta u config.json i bank_solo/config.json koja govore o kodu
   tečaja kojeg nema ni u jednoj tablici, ali vrlo nalikuje jednom od njih -
   i prepiše ih na pravopis iz tablice.

Drugi korak NE pogađa kod tečaja koji tablicu još nema. To je uredno stanje,
ne greška: 'course_codes' postoji upravo zato da se prijava prepozna i prije
nego tablica nastane. Zato se predlaže samo ime koje se od onog u tablici
razlikuje u SLOVIMA, a ima iste cifre - 'praktočarski' i 'praktičarski' jesu
isti tečaj, 'Modul 3' i 'Modul 4' nisu, koliko god nalikovali.

Pokretanje (bez --stvarno samo ispiše što bi promijenio):
    ~/Tgdgd/server/pokreni.sh uskladi_kodove.py
    ~/Tgdgd/server/pokreni.sh uskladi_kodove.py --stvarno

Prije izmjene se napravi kopija: tablica u mapu 'Kopije', a config u
config.json.prije-uskladivanja.
"""

import argparse
import difflib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import prava
import tablice
from predlosci import kljuc_tecaja
from send_reminders import CELL_COURSE_CODE, CELL_DATES, CELL_LOCATION
from zoho_to_excel import load_config, with_retry

MAPA_KOPIJA = "Kopije"

# Koliko dva imena moraju nalikovati da se prepisivanje uopće predloži.
#
# Prag je izmjeren na stvarnim imenima, ne pogođen. difflib ratio:
#   'ponavljanje modula 6 i praktocarski dan' ~ 'ponavljanje m6 i
#   prakticarski dan'  = 0.889   <- isti tečaj, mora proći
#   'modul 6' ~ 'modul 6 obnova'              = 0.667   <- različita, ne smije
#   'modul 1&2' ~ 'modul 2'                   = 0.875   <- različita, ali tu
#                                                  presuđuju cifre, ne prag
SLICNOST = 0.80

# Gdje u konfiguraciji stoji kod tečaja. (datoteka, polje, oblik)
# "popis"  - lista kodova
# "kljucevi" - rječnik kojem su kodovi ključevi
MJESTA = [
    ("config.json", "course_codes", "popis"),
    ("config.json", "deposit_course_codes", "popis"),
    ("config.json", "no_certificate_course_codes", "popis"),
    ("config.json", "module_order", "popis"),
    ("config.json", "certificate_templates", "kljucevi"),
    ("config.json", "print_items", "kljucevi"),
    ("bank_solo/config.json", "course_description_map", "kljucevi"),
]


def samo_razmaci(tekst: str) -> str:
    """Isti tekst bez viška razmaka. Slova se ne diraju."""
    return " ".join(str(tekst).split())


def cifre(tekst: str) -> str:
    """Cifre u tekstu, u istom redu: 'Modul 1&2' -> '12'."""
    return "".join(re.findall(r"\d", str(tekst)))


def pospremi_tablice(output_dir: Path, stvarno: bool) -> tuple:
    """(kodovi iz tablica, broj pospremljenih ćelija)."""
    kodovi, pospremljeno = {}, 0
    for put in tablice.nadji(output_dir, javi=lambda poruka: print(f"  {poruka}")):
        wb = with_retry(lambda: load_workbook(put), retry_on=(PermissionError, OSError))
        if "podaci" not in wb.sheetnames:
            print(f"  [!] {put.name} nema list 'podaci' - preskačem.")
            continue
        ws = wb["podaci"]
        izmjene = []
        for celija in (CELL_COURSE_CODE, CELL_LOCATION, CELL_DATES):
            staro = ws[celija].value
            if not isinstance(staro, str):
                continue
            novo = samo_razmaci(staro)
            if novo != staro:
                izmjene.append((celija, staro, novo))

        kod = samo_razmaci(ws[CELL_COURSE_CODE].value or "")
        if kod:
            kodovi.setdefault(kljuc_tecaja(kod), kod)

        if not izmjene:
            continue
        print(f"  {put.name}")
        for celija, staro, novo in izmjene:
            print(f"    {celija}: {staro!r} -> {novo!r}")
        pospremljeno += len(izmjene)
        if not stvarno:
            continue
        kopija = (prava.mapa(put.parent / MAPA_KOPIJA)
                  / f"{put.stem} prije uskladivanja "
                    f"{datetime.now():%Y-%m-%d %H-%M-%S}.xlsx")
        prava.kopiraj(put, kopija)
        for celija, _, novo in izmjene:
            ws[celija] = novo
        with_retry(lambda: wb.save(put), retry_on=(PermissionError, OSError))
        print(f"    upisano (kopija: {MAPA_KOPIJA}/{kopija.name})")
    return kodovi, pospremljeno


def preimenovanje(stari: str, novi: str):
    """Pravilo za --preimenuj: prepiši svaki zapis koji je taj kod."""
    trazeni = kljuc_tecaja(stari)

    def pravilo(zapis: str, kodovi: dict):
        return novi if kljuc_tecaja(zapis) == trazeni else None
    return pravilo


def predlozi(zapis: str, kodovi: dict):
    """Kod iz tablice na koji ovaj zapis očito misli, ili None.

    Traži se samo kad zapisa nema ni u jednoj tablici. Cifre moraju biti
    iste, da 'Modul 3' nikad ne postane 'Modul 4', i kandidat mora biti
    jedan jedini - inače se ne dira ništa."""
    kljuc = kljuc_tecaja(zapis)
    if kljuc in kodovi:
        return None                      # već se poklapa
    moguci = [k for k in kodovi if cifre(k) == cifre(kljuc)]
    blizu = difflib.get_close_matches(kljuc, moguci, n=2, cutoff=SLICNOST)
    if len(blizu) != 1:
        return None
    return kodovi[blizu[0]]


def uskladi_config(put: Path, naziv: str, polja: list, kodovi: dict,
                   stvarno: bool, pravilo=predlozi) -> tuple:
    """(broj izmjena, kodovi koje nijedna tablica ne koristi)."""
    if not put.exists():
        print(f"  [!] nema {put} - preskačem.")
        return 0, []
    with open(put, encoding="utf-8") as f:
        config = json.load(f)

    izmjene, bez_tablice = [], []

    def pogledaj(polje, zapis, gdje):
        novo = pravilo(zapis, kodovi)
        if novo and kljuc_tecaja(novo) != kljuc_tecaja(zapis):
            izmjene.append((polje, zapis, novo, gdje))
        elif not novo and kljuc_tecaja(zapis) not in kodovi:
            bez_tablice.append((polje, zapis))

    for polje, oblik in polja:
        vrijednost = config.get(polje)
        if oblik == "popis" and isinstance(vrijednost, list):
            for i, zapis in enumerate(vrijednost):
                if isinstance(zapis, str):
                    pogledaj(polje, zapis, ("popis", i))
        elif oblik == "kljucevi" and isinstance(vrijednost, dict):
            for zapis in list(vrijednost):
                pogledaj(polje, zapis, ("kljuc", zapis))

    if not izmjene:
        return 0, bez_tablice

    print(f"  {naziv}")
    for polje, staro, novo, _ in izmjene:
        print(f"    {polje}: {staro!r} -> {novo!r}")
    if not stvarno:
        return len(izmjene), bez_tablice

    for polje, staro, novo, (vrsta, gdje) in izmjene:
        if vrsta == "popis":
            config[polje][gdje] = novo
        else:
            # novi ključ na mjesto starog, da red u datoteci ostane isti
            config[polje] = {(novo if k == gdje else k): v
                             for k, v in config[polje].items()}

    kopija = put.with_name(put.name + ".prije-uskladivanja")
    prava.kopiraj(put, kopija)
    privremeno = put.with_name(put.name + ".tmp")
    with open(privremeno, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    privremeno.replace(put)
    prava.zakljucaj(put)
    print(f"    upisano (kopija: {kopija.name})")
    return len(izmjene), bez_tablice


def main():
    parser = argparse.ArgumentParser(
        description="Uskladi kodove tečajeva u tablicama i konfiguraciji.")
    parser.add_argument("--stvarno", action="store_true",
                        help="Stvarno upiši; bez ovoga je samo pregled")
    parser.add_argument("--preimenuj", nargs=2, metavar=("STARI", "NOVI"),
                        help="Prepiši točno taj kod, bez traženja po "
                             "sličnosti - za slučaj koji skripta ne pogodi "
                             "sama")
    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    print("1. Razmaci u ćelijama C4, C5 i C6")
    kodovi, pospremljeno = pospremi_tablice(output_dir, args.stvarno)
    if not pospremljeno:
        print("  sve je uredno")
    if not kodovi:
        sys.exit("\nNijedna tablica nema kod tečaja u C4 - ne znam s čim bih "
                 "uskladio config, pa ne diram ništa.")

    print(f"\nKodovi iz tablica ({len(kodovi)}):")
    for kod in sorted(kodovi.values()):
        print(f"  {kod}")

    print("\n2. Kodovi u konfiguraciji")
    pravilo = (preimenovanje(*args.preimenuj) if args.preimenuj else predlozi)
    korijen = Path(__file__).resolve().parent
    ukupno, bez_tablice = 0, []
    for naziv in dict.fromkeys(d for d, _, _ in MJESTA):
        polja = [(p, o) for d, p, o in MJESTA if d == naziv]
        broj, nepoznati = uskladi_config(korijen / naziv, naziv, polja,
                                         kodovi, args.stvarno, pravilo)
        ukupno += broj
        bez_tablice += [(naziv, polje, zapis) for polje, zapis in nepoznati]
    if not ukupno:
        print("  ništa se ne da uskladiti samo")

    # Sve što ostaje neusklađeno mora se vidjeti, da ne ostane tiho pokvareno.
    if bez_tablice and not args.preimenuj:
        print("\n3. Kodovi u configu koje nijedna tablica ne koristi")
        print("   Uredno je dok tečaj nije imao prijava - tablica nastane s")
        print("   prvom. Ako bi je trebao imati, kod se negdje razlikuje.")
        gdje = {}
        for naziv, polje, zapis in bez_tablice:
            gdje.setdefault(zapis, []).append(f"{naziv}:{polje}")
        for zapis in sorted(gdje):
            print(f"  {zapis!r} - {', '.join(gdje[zapis])}")
        print("\n   Ako je neki od njih pogrešno napisan isti tečaj, prepiši "
              "ga izravno:")
        print('    ~/Tgdgd/server/pokreni.sh uskladi_kodove.py \\')
        print('        --preimenuj "<kod iz configa>" "<kod iz tablice>" '
              '--stvarno')

    if (pospremljeno or ukupno) and not args.stvarno:
        print("\nPregled - ništa nije promijenjeno. Za upis dodaj --stvarno")
    elif pospremljeno or ukupno:
        print("\nGotovo. Provjeri da se potvrdnice nalaze:")
        print("    ~/Tgdgd/server/pokreni.sh napravi_certifikate.py --pregled")
    else:
        print("\nNema se što uskladiti.")


if __name__ == "__main__":
    main()
