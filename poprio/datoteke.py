"""Stvaranje mapa i datoteka tako da im ne može pristupiti nitko drugi.

Na jednom mjestu namjerno: isti propust se inače zatvori na jednoj putanji, a
na drugoj ostane. Dva obrasca koja ovo pokriva:

- `mkdir(exist_ok=True)` nad POSTOJEĆOM mapom ne dira njena prava. Mapa
  nastala ranije s labavijim pravima tako zauvijek ostaje otvorena, iako kod
  "stvara" privatnu mapu.
- bez umaska datoteke nastaju po zadanom (najčešće 644), pa zaštićena mapa
  drži nezaštićen sadržaj. Dok god mapa stoji, to se ne vidi - a kad prava
  mape jednom popuste, sve unutra je odjednom čitljivo.
"""

import os
import sys
from pathlib import Path

PRIVATNA_MAPA = 0o700
PRIVATNE_DATOTEKE = 0o077  # umask: sve novo nastaje kao 600


def postavi_umask():
    """Da baza, zaključavanje i privremene datoteke nastaju kao 600.

    SQLite bazu stvara sam sqlite3 i prava joj se ne mogu zadati pozivom, pa
    je umask jedini način da ne nastane kao 644."""
    os.umask(PRIVATNE_DATOTEKE)


def privatna_mapa(putanja):
    """Mapa koja postoji i koju vidi samo vlasnik.

    Prava se NE popravljaju nasilno: `state_db_path` iz configa može
    pokazivati i na dijeljenu sistemsku mapu, pa bi `chmod 700` nad njom
    srušio pola sustava. Umjesto toga se glasno javlja, a ispravak je jedna
    naredba koju čovjek izvrši svjesno."""
    p = Path(putanja)
    p.mkdir(parents=True, exist_ok=True, mode=PRIVATNA_MAPA)

    prava = p.stat().st_mode & 0o777
    if prava & 0o077:
        print(
            f"[UPOZORENJE] {p} je dostupna i drugim korisnicima (prava "
            f"{prava:o}), a u njoj su podaci pacijenata.\n"
            f"  Ispravi s:  chmod 700 {p}",
            file=sys.stderr,
        )
    return p
