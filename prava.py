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
    755 zauvijek. Zato `mapa()` - ali samo za mape koje sami pravimo.

Mapu koju je zadao korisnik (`output_dir` iz config.json, `EMMETT_ZAHTJEVI`)
NE popravljamo nasilno, nego samo javimo - vidi `mapa_iz_postavki()`.

Oboje je isti obrazac zbog kojeg je web/stanje.json bio 644: original je bio
zaštićen, a izvedenica iz njega nije.
"""

import os
import shutil
import stat
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
    """Mapa koju sami pravimo - stvori ju i stegni prava, i staru.

    Samo za mape unutar naših: Popisi, Certifikati, Izvjesca, Kopije,
    obradeno. Njih nitko drugi ne koristi, pa je prisilni chmod siguran.
    Za mapu iz konfiguracije postoji `mapa_iz_postavki()`."""
    put = Path(put)
    put.mkdir(parents=True, exist_ok=True)
    return zakljucaj(put)


# Da se isto upozorenje ne ponavlja pri svakom pozivu (web ga zove na svaki
# zahtjev i svaki promašaj prijave).
_javljeno = set()


def mapa_iz_postavki(put, javi=print) -> Path:
    """Mapa koju je zadao korisnik - stvori ju ako je nema, inače samo javi.

    Ovdje se prava NAMJERNO ne popravljaju. Put dolazi iz config.json
    (`output_dir`) ili iz okoline (`EMMETT_ZAHTJEVI`) i može pokazivati na
    mapu koja nije naša - iCloud Drive, /tmp, dijeljenu sistemsku mapu. Naš
    `chmod 700` nad takvom mapom napravio bi više štete nego koristi, a čija
    je mapa ne znamo iz koda.

    Ako mape nema, nastaje kroz umask i time je odmah zaštićena. Ako postoji
    i otvorena je drugima, javi se jednom po pokretanju i posao ide dalje.

    Ovako je zato što je Poprio tim na to upozorio: do istog su zaključka
    došli na svojoj strani, gdje put do baze pacijenata dolazi iz
    konfiguracije."""
    put = Path(put)
    if not put.exists():
        put.mkdir(parents=True, exist_ok=True)      # umask -> 700
        return put
    try:
        sada = stat.S_IMODE(put.stat().st_mode)
    except OSError:
        return put
    if sada & 0o077 and str(put) not in _javljeno:
        _javljeno.add(str(put))
        javi(f"[!] {put} ima prava {sada:o} - čitljiva je drugim korisnicima "
             f"stroja, a u njoj su podaci polaznika. Ne mijenjam ih sam jer je "
             f"put zadan u postavkama. Zatvori ju s:  chmod go= {put}")
    return put
