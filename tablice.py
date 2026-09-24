"""
Pronalaženje Excel tablica tečajeva - i zaštita od dvije zamke koje donosi
sinkronizirani folder (iCloud, Dropbox i slično).

1. DATOTEKA U OBLAKU. Kad macOS oslobađa prostor, pravu datoteku zamijeni
   praznim tragom ('.Modul 1&2 Split.xlsx.icloud'). Taj trag ne završava na
   .xlsx, pa ga skripte ne vide - tečaj bi jednostavno nestao iz obrade, bez
   ijedne greške. Zato se traži izrijekom i glasno javlja.

2. KOPIJA S SUKOBOM. Ako je tablica otvorena u Excelu dok skripta u nju piše,
   sinkronizacija zna napraviti drugu datoteku ('Modul 1&2 Split 2.xlsx').
   Učitala bi se kao zaseban tečaj: polaznici bi se brojali dvaput, a uplata
   bi mogla završiti u staroj kopiji. Takva se datoteka NE obrađuje.

   Datoteka se smatra kopijom samo ako uz nju postoji i original istog
   naziva - tako se nijedna stvarna tablica ne može slučajno izbaciti.
"""

import re
from pathlib import Path

import predlosci

PREDLOZAK = "template_admin_sheet.xlsx"

# Nazivi koje sinkronizacija i Finder dodaju kopiji.
_SUFIKS_KOPIJE = re.compile(r"^(?P<osnova>.+?)\s*(?:\(\d+\)|\d+)$")
_OCITA_KOPIJA = re.compile(r"(conflicted copy|kopija|copy)", re.IGNORECASE)


def u_oblaku(mapa) -> dict:
    """{pravi naziv datoteke: put do traga} za sve datoteke koje je
    sinkronizacija izbacila u oblak."""
    mapa = Path(mapa)
    if not mapa.is_dir():
        return {}
    nadjeno = {}
    for put in mapa.iterdir():
        if put.suffix.lower() != ".icloud" or not put.name.startswith("."):
            continue
        nadjeno[put.name[1:-len(".icloud")]] = put
    return nadjeno


def _zasto_kopija(put: Path, postojeci: set):
    """Ako je datoteka kopija, vrati objašnjenje za log; inače None."""
    if _OCITA_KOPIJA.search(put.stem):
        return "u nazivu joj piše da je kopija s sukobom"
    m = _SUFIKS_KOPIJE.match(put.stem)
    if not m:
        return None
    original = f"{m.group('osnova')}{put.suffix}"
    if original in postojeci:
        return f"naziv joj je {original} s dodanim brojem, a original postoji"
    return None


def nadji(mapa, javi=print) -> list:
    """Vrati popis tablica tečajeva koje se smiju obrađivati.

    Preskače Excelove privremene datoteke (~$), predložak i kopije s
    sukobom, a sve što preskoči ili nađe u oblaku javi preko `javi`."""
    mapa = Path(mapa)
    svi = sorted(p for p in mapa.glob("*.xlsx")
                 if not p.name.startswith("~$") and p.name != PREDLOZAK)
    imena = {p.name for p in svi}

    for naziv, trag in sorted(u_oblaku(mapa).items()):
        javi(f"[!] {naziv} nije na disku nego u oblaku ({trag.name}) - "
             f"ne mogu je pročitati. Otvori folder u Finderu i pričekaj da se "
             f"preuzme, ili desni klik na folder -> Keep Downloaded.")

    upotrebljive = []
    for put in svi:
        zasto = _zasto_kopija(put, imena)
        if zasto:
            javi(f"[!] {put.name} - {zasto}, pa je NE obrađujem. Usporedi je s "
                 f"originalom i obriši onu koja ne treba; dok postoji, podaci "
                 f"iz nje se nigdje ne koriste.")
            continue
        upotrebljive.append(put)

    return upotrebljive


def trag_u_oblaku(mapa, naziv: str):
    """Je li dokument tog naziva (bez nastavka) izbačen u oblak? Vrati pravi
    naziv datoteke ili None. Koristi se da se 'nema dokumenta' razlikuje od
    'dokument postoji, ali nije preuzet' - dvije posve različite stvari."""
    if not naziv:
        return None
    trazeno = predlosci.bez_dijakritika(naziv)
    for pravi in u_oblaku(mapa):
        if predlosci.bez_dijakritika(Path(pravi).stem) == trazeno:
            return pravi
    return None
