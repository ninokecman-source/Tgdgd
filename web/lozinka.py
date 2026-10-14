"""
Lozinka za web pregled - izrada i provjera zapisa.

Zapis koji ide u config.json izgleda tako:

    scrypt$16384$8$1$<sol u hexu>$<hash u hexu>

Čuva se samo hash, nikad sama lozinka. scrypt je iz standardne knjižnice,
pa za ovo ne treba nijedan dodatni paket.
"""

import hashlib
import hmac
import os

N, R, P = 16384, 8, 1
DULJINA = 32


def napravi(lozinka: str) -> str:
    sol = os.urandom(16)
    hash_ = hashlib.scrypt(lozinka.encode("utf-8"), salt=sol,
                           n=N, r=R, p=P, dklen=DULJINA)
    return f"scrypt${N}${R}${P}${sol.hex()}${hash_.hex()}"


def provjeri(zapis: str, lozinka: str) -> bool:
    try:
        vrsta, n, r, p, sol_hex, hash_hex = zapis.split("$")
        if vrsta != "scrypt":
            return False
        hash_ = hashlib.scrypt(lozinka.encode("utf-8"), salt=bytes.fromhex(sol_hex),
                               n=int(n), r=int(r), p=int(p),
                               dklen=len(hash_hex) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(hash_.hex(), hash_hex)
