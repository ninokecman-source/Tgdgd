"""
Upiši u config.json adresu tiskare i što ide na print uz koji modul.

Dva polja:

  print_email  - kome ide narudžba
  print_items  - što sve ide uz koji modul, i u koliko primjeraka

Ključ u `print_items` mora biti kod tečaja onako kako piše u ćeliji C4 te
tablice, jer se po njemu i traži (preko kljuc_tecaja, pa kvačice i velika
slova nisu važni - slova jesu). Zato ovdje ne pišem kodove iz glave nego ih
čitam iz tablica. Ako se ključ ne poklopi, narudžba tiho ispadne nepotpuna:
pošalje se samo skripta, bez disclaimera, obrasca i potvrdnica.

Predlažu se samo moduli kojima uz skriptu ide još nešto. Za ostale nema što
upisivati - bez zapisa posalji_na_print.py ionako šalje skriptu imenovanu po
kodu tečaja, što je točno ono što treba.

Postojeći zapisi se ne diraju. Skripta usput provjeri jesu li imenovane
datoteke u mapi Print i javi koje nema.

Pokretanje (bez --stvarno samo ispiše što bi upisao):
    ~/Tgdgd/server/pokreni.sh postavi_print.py
    ~/Tgdgd/server/pokreni.sh postavi_print.py --email tiskara@primjer.com
    ~/Tgdgd/server/pokreni.sh postavi_print.py --email ... --stvarno
"""

import argparse
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

import prava
import tablice
from posalji_na_print import ZADANA_MAPA, nadji_datoteku
from predlosci import kljuc_tecaja
from send_reminders import CELL_COURSE_CODE
from zoho_to_excel import load_config, with_retry

CONFIG = Path(__file__).resolve().parent / "config.json"

# Što ide uz koji modul. Prepoznaje se po dijelu koda tečaja, malim slovima i
# bez kvačica, jer tablice ispunjava čovjek pa se zapis razlikuje.
#
#   koliko: "polaznici" (koliko ih je), "pola" (pola toliko, gore), ili broj
#   certifikati: sve gotove potvrdnice tog tečaja, svaka u jednom primjerku
PRAVILA = [
    ("modul 1&2", [
        {"datoteka": "Disclaimer"},
        {"datoteka": "Zdravstveni obrazac", "koliko": "pola"},
    ]),
    ("ponavljanje", [
        {"datoteka": "Praktičarski ispit"},
        {"certifikati": True, "papir": "tvrđi papir"},
    ]),
]


def kodovi_iz_tablica(output_dir: Path) -> list:
    kodovi = []
    for put in tablice.nadji(output_dir, javi=lambda poruka: print(f"  {poruka}")):
        wb = with_retry(lambda: load_workbook(put), retry_on=(PermissionError, OSError))
        if "podaci" not in wb.sheetnames:
            continue
        kod = " ".join(str(wb["podaci"][CELL_COURSE_CODE].value or "").split())
        if kod and kod not in kodovi:
            kodovi.append(kod)
    return kodovi


def stavke_za_kod(kod: str) -> list:
    """Što uz skriptu ide na print za taj kod tečaja, ili [] ako samo skripta."""
    kljuc = kljuc_tecaja(kod)
    for dio, stavke in PRAVILA:
        if kljuc_tecaja(dio) in kljuc:
            return [{"datoteka": kod}] + [dict(s) for s in stavke]
    return []


def main():
    parser = argparse.ArgumentParser(
        description="Upiši adresu tiskare i popis za print u config.json.")
    parser.add_argument("--email", help="Adresa tiskare (print_email)")
    parser.add_argument("--stvarno", action="store_true",
                        help="Stvarno upiši; bez ovoga je samo pregled")
    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    print("Kodovi tečajeva iz tablica:")
    kodovi = kodovi_iz_tablica(output_dir)
    for kod in kodovi:
        print(f"  {kod}")
    if not kodovi:
        sys.exit("\nNijedna tablica nema kod tečaja u C4 - ne znam što bih "
                 "upisao, pa ne diram config.")

    # --- adresa ---------------------------------------------------------
    stara_adresa = (config.get("print_email") or "").strip()
    nova_adresa = (args.email or "").strip()
    print("\nAdresa tiskare (print_email)")
    if nova_adresa and "@" not in nova_adresa:
        sys.exit(f"  {nova_adresa!r} ne izgleda kao adresa.")
    if nova_adresa and nova_adresa != stara_adresa:
        print(f"  {stara_adresa or '(nije upisana)'} -> {nova_adresa}")
    elif stara_adresa:
        print(f"  ostaje {stara_adresa}")
    else:
        print("  nije upisana - dodaj --email, inače slanje u tiskaru neće "
              "raditi")

    # --- stavke ---------------------------------------------------------
    postojece = dict(config.get("print_items") or {})
    imaju = {kljuc_tecaja(k) for k in postojece}
    novi = {}
    print("\nŠto ide na print (print_items)")
    for kod in kodovi:
        stavke = stavke_za_kod(kod)
        if not stavke:
            print(f"  {kod}: samo skripta - nema što upisivati")
            continue
        if kljuc_tecaja(kod) in imaju:
            print(f"  {kod}: već upisan, ne diram")
            continue
        novi[kod] = stavke
        print(f"  {kod}:")
        for s in stavke:
            if s.get("certifikati"):
                print(f"    - sve potvrdnice tog tečaja, {s['papir']}")
            else:
                koliko = {"pola": "pola broja polaznika",
                          None: "koliko i polaznika"}.get(s.get("koliko"),
                                                          s.get("koliko"))
                print(f"    - {s['datoteka']}: {koliko}")

    # --- jesu li datoteke u mapi Print ----------------------------------
    mapa_print = output_dir / config.get("print_folder", ZADANA_MAPA)
    print(f"\nDatoteke u mapi {mapa_print.name}")
    trazene = []
    for stavke in list(novi.values()) + list(postojece.values()):
        for s in stavke if isinstance(stavke, list) else []:
            naziv = s.get("datoteka")
            if naziv and naziv not in trazene:
                trazene.append(naziv)
    fali = []
    for naziv in trazene:
        put = nadji_datoteku(mapa_print, naziv) if mapa_print.is_dir() else None
        print(f"  {'ima' if put else 'NEMA'}  {naziv}"
              + (f"  ({put.name})" if put else ""))
        if not put:
            fali.append(naziv)
    if fali:
        print(f"\n  Stavi ih u {mapa_print} - nastavak nije važan (.pdf, .docx),")
        print("  naziv jest. Bez njih slanje u tiskaru odbija poslati "
              "nepotpunu narudžbu.")

    # --- upis -----------------------------------------------------------
    mijenjam = bool(novi) or (nova_adresa and nova_adresa != stara_adresa)
    if not mijenjam:
        print("\nNema se što upisati.")
        return
    if not args.stvarno:
        print("\nPregled - ništa nije upisano. Za upis dodaj --stvarno")
        return

    with open(CONFIG, encoding="utf-8") as f:
        na_disku = json.load(f)
    if nova_adresa:
        na_disku["print_email"] = nova_adresa
    if novi:
        na_disku["print_items"] = {**postojece, **novi}

    kopija = CONFIG.with_name(CONFIG.name + ".prije-printa")
    prava.kopiraj(CONFIG, kopija)
    privremeno = CONFIG.with_name(CONFIG.name + ".tmp")
    with open(privremeno, "w", encoding="utf-8") as f:
        json.dump(na_disku, f, ensure_ascii=False, indent=2)
        f.write("\n")
    privremeno.replace(CONFIG)
    prava.zakljucaj(CONFIG)
    print(f"\nUpisano u {CONFIG.name} (kopija: {kopija.name}).")
    print("Provjeri narudžbu, bez slanja:")
    print('    ~/Tgdgd/server/pokreni.sh posalji_na_print.py --tecaj "Modul 1&2 Split.xlsx"')


if __name__ == "__main__":
    main()
