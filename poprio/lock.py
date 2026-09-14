"""Zaključavanje koje sprječava da dvije kopije skripte rade istovremeno.

Dva paralelna procesa mogu isti Cliniko račun poslati u Solo dvaput (oba
prođu provjeru "je li obrađen" prije nego ijedan stigne zapisati da jest).
Tipični uzroci: systemd servis uz zaboravljen cron unos, dva `docker run`,
ili ručno pokretanje dok servis radi.

Koristi se `flock`, koji operativni sustav sam otpušta kad proces završi -
i kad uredno izađe i kad ga se ubije - pa nema zaostalih zaključavanja koja
bi trebalo ručno čistiti.

VAŽNO: zaključavanje vrijedi samo unutar jednog stroja. Ako se skripta
pokrene na dva različita servera s istim Solo tokenom (npr. stari server
ostane raditi nakon preseljenja), ovo ju neće zaustaviti.
"""

import fcntl
from contextlib import contextmanager
from pathlib import Path


class AlreadyRunning(Exception):
    pass


@contextmanager
def single_instance(lock_path):
    """Drži ekskluzivno zaključavanje dok traje blok. Diže AlreadyRunning ako
    ga već drži neki drugi proces."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    handle = path.open("w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise AlreadyRunning(str(path)) from e
        yield
    finally:
        handle.close()
