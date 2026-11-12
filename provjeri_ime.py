"""
Gdje sustav vidi neko ime.

Služi kad se ime polaznika ispravi u tablici, a aplikacija ili potvrdnica i
dalje pokazuju staro. I jedno i drugo čitaju ime izravno iz tablice, pa
razlika uvijek znači da negdje stoji druga tablica, drugi redak ili starija
snimka - a ova provjera kaže koje od toga.

Prođe sve .xlsx u folderu s tablicama (i kopije i sukobe sinkronizacije, jer
upravo one zavaravaju), sve PDF-ove potvrdnica, i snimku koju čita web.

Pokretanje - uvijek kroz pokreni.sh, da prvo povuče svježe iz Dropboxa:

    ~/Tgdgd/server/pokreni.sh provjeri_ime.py Daniela Danijela

Traži se po dijelu imena, bez obzira na velika slova i kvačice, pa je dovoljno
i:  provjeri_ime.py gluhan
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import predlosci
import tablice
from zoho_to_excel import (FIRST_PARTICIPANT_ROW, find_totals_row, load_config,
                           with_retry)

SNIMKA = Path(__file__).with_name("web") / "stanje.json"

COL_IME, COL_PREZIME, COL_EMAIL = 2, 3, 8


def kljuc(tekst) -> str:
    return predlosci.bez_dijakritika(str(tekst or "").strip().lower())


def pogada(tekst, trazeno: list) -> bool:
    k = kljuc(tekst)
    return any(t in k for t in trazeno)


def kada(put: Path) -> str:
    return datetime.fromtimestamp(put.stat().st_mtime).strftime("%d.%m.%Y. %H:%M")


def otvori(put: Path):
    """openpyxl odbija nastavak koji ne poznaje, a sukob koji ostavi rclone
    zove se '....xlsx.conflict1' - iznutra je obicna tablica. Zato se daje
    otvorena datoteka, ne put: tada se nastavak ne gleda."""
    with open(put, "rb") as f:
        return load_workbook(f)


def prodji_tablicu(put: Path, trazeno: list) -> list:
    """[(redak, ime, prezime, email)] za retke koji odgovaraju."""
    try:
        wb = with_retry(lambda: otvori(put), retry_on=(PermissionError, OSError))
    except Exception as e:
        print(f"  [!] {put.name}: ne mogu otvoriti ({e})")
        return []
    if "podaci" not in wb.sheetnames:
        return []
    ws = wb["podaci"]
    nadjeno = []
    for row in range(FIRST_PARTICIPANT_ROW, find_totals_row(ws)):
        ime = ws.cell(row=row, column=COL_IME).value
        prezime = ws.cell(row=row, column=COL_PREZIME).value
        if not ime and not prezime:
            continue
        if pogada(f"{ime or ''} {prezime or ''}", trazeno):
            nadjeno.append((row, ime, prezime,
                            ws.cell(row=row, column=COL_EMAIL).value))
    return nadjeno


def main():
    trazeno = [kljuc(a) for a in sys.argv[1:] if kljuc(a)]
    if not trazeno:
        print(__doc__.strip())
        return 2

    config = load_config()
    mapa = Path(config["output_dir"])
    if not mapa.is_dir():
        print(f"[!] Ne postoji folder s tablicama: {mapa}")
        return 1

    print(f"Tražim {', '.join(sys.argv[1:])} u {mapa}\n")

    # 1. Tablice. Namjerno sve, ne samo one koje sustav obrađuje: ispravak
    # koji je zavrsio u kopiji ili u sukobu sinkronizacije je upravo ono sto
    # se ovdje trazi, a takva se datoteka nigdje drugdje ne cita. Sukobi koje
    # ostavi rclone ne zavrsavaju na .xlsx, pa se dodaju izrijekom.
    obraduju = {p.name for p in tablice.nadji(mapa, javi=lambda _: None)}
    sukobi = tablice.sukobi_sinkronizacije(mapa)
    svi = sorted(p for p in mapa.rglob("*.xlsx")
                 if not p.name.startswith("~$") and p.name != tablice.PREDLOZAK)

    print("== Tablice ==")
    nadjeno_igdje = False
    for put in svi + sukobi:
        retci = prodji_tablicu(put, trazeno)
        if not retci:
            continue
        nadjeno_igdje = True
        cita = "" if put.name in obraduju else "   <- OVU SUSTAV NE ČITA"
        print(f"\n{put.relative_to(mapa)}   (zadnja izmjena {kada(put)}){cita}")
        for row, ime, prezime, email in retci:
            print(f"  redak {row}: ime={ime!r} prezime={prezime!r} email={email!r}")
    if not nadjeno_igdje:
        print("  Nijedna tablica ne sadrži to ime.")

    # 2. Zasto neku ne cita, pa i ona koja nema trazeno ime.
    upozorenja = []
    tablice.nadji(mapa, javi=upozorenja.append)
    if upozorenja:
        print("\n== Datoteke koje sustav ne čita ==")
        for poruka in upozorenja:
            print(f"  {poruka}")

    # 3. Potvrdnice.
    print("\n== Potvrdnice ==")
    pdfovi = [p for p in sorted(mapa.rglob("*.pdf")) if pogada(p.stem, trazeno)]
    for put in pdfovi:
        print(f"  {put.relative_to(mapa)}   ({kada(put)})")
    if not pdfovi:
        print("  Nema nijednog PDF-a s tim imenom.")

    # 4. Snimka koju cita web. Ona je razlog zasto stranica zna kasniti:
    # osvjezava se svakih 20 minuta, pa svjeza tablica i stara stranica nisu
    # proturjecje nego cekanje.
    print("\n== Što aplikacija trenutno pokazuje ==")
    if not SNIMKA.exists():
        print("  Nema snimke (web/stanje.json).")
    else:
        podaci = json.loads(SNIMKA.read_text(encoding="utf-8"))
        print(f"  Snimka napravljena: {podaci.get('snimljeno', '?')}"
              f"   (tablice gore čitam upravo sada)")
        imena = [(t.get("datoteka", "?"), p.get("ime", ""))
                 for t in podaci.get("tecajevi", [])
                 for p in t.get("polaznici", []) if pogada(p.get("ime"), trazeno)]
        for datoteka, ime in imena:
            print(f"  {datoteka}: {ime!r}")
        if not imena:
            print("  U snimci nema nikoga s tim imenom.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
