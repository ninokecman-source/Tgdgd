"""
Prava na novim datotekama - jedno mjesto za sve skripte.

Kroz ovaj sustav idu imena, adrese, mailovi i mobiteli polaznika, a server
dijelimo s drugom aplikacijom. Nijedna datoteka koju napravimo ne smije biti
čitljiva drugim korisnicima stroja.

Zadani umask (022) daje 644 i 755. Ovaj modul ga čim je uvezen pomiče na 077:
od tada svaka nova datoteka nastaje kao 600, a svaka nova mapa kao 700. Zato
se u svakoj skripti koja se pokreće nalazi `import prava` i ništa više.

Umask stoji i u server/postavke.sh, pa vrijedi za cron i rclone. Ali skripta
pokrenuta rukom iz shella ne prolazi kroz postavke.sh, a i tada mora nastati
zaštićena datoteka - zato ide i u kod, ne samo u pokretač.

Dvije stvari umask ne pokriva, i za njih su funkcije ispod:

  - `shutil.copy2` prepisuje prava izvora na kopiju i umask preskače. Je li
    izvor 644, kopija je 644, koliko god umask bio strog. Zato `kopiraj()`.
  - `mkdir(exist_ok=True)` ne dira mapu koja već postoji, pa stara ostaje
    755 zauvijek. Zato `mapa()`.

Oboje je isti obrazac zbog kojeg je web/stanje.json bio 644: original je bio
zaštićen, a izvedenica iz njega nije.
"""

import os
import shutil
from pathlib import Path

DATOTEKA = 0o600
MAPA = 0o700

os.umask(0o077)


def zakljucaj(put) -> Path:
    """Suzi prava na datoteci ili mapi, kako god nastala.

    Greška se preskače namjerno: ako se prava ne daju promijeniti (tuđa
    datoteka, mapa samo za čitanje), posao se zbog toga ne prekida - nego se
    nastavlja, jer je sve ostalo već napravljeno."""
    put = Path(put)
    try:
        put.chmod(MAPA if put.is_dir() else DATOTEKA)
    except OSError:
        pass
    return put


def kopiraj(izvor, cilj) -> Path:
    """Kopija koja ne nasljeđuje preširoka prava izvora."""
    shutil.copy2(izvor, cilj)
    return zakljucaj(cilj)


def mapa(put) -> Path:
    """Mapa koja postoji i nije čitljiva drugima - i kad je zatekne staru."""
    put = Path(put)
    put.mkdir(parents=True, exist_ok=True)
    return zakljucaj(put)
