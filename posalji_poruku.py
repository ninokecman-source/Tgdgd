"""
Pošalji jednu poruku jednom čovjeku - tekst onakav kakav mu je zadan.

Služi tipkama na web stranici (npr. "Podsjetnik za plaćanje"), gdje tekst
prije slanja proći kroz tvoje ruke. Zato se ovdje ništa ne popunjava i ne
dotjeruje: naslov i tijelo dolaze iz datoteka i šalju se nedirnuti. Oznake
poput {first_name} ovdje se NE zamjenjuju - to se dogodilo ranije, dok si
tekst gledao na ekranu.

Tekst stiže u datotekama, a ne kao argument naredbe, iz dva razloga: duga
poruka ne stane u naredbu, a tako ni jedan navodnik ni novi red ne mogu
ništa pokvariti.

Pokretanje:
    python3 posalji_poruku.py --kome ana@primjer.hr \\
        --naslov-datoteka naslov.txt --tijelo-datoteka tijelo.txt   # pregled
    python3 posalji_poruku.py ... --stvarno                          # pošalji
"""

import argparse
import mimetypes
import sys
from email.message import EmailMessage
from pathlib import Path

from zoho_to_excel import load_config, with_retry

import posta


def procitaj(put_tekst: str, sto: str) -> str:
    put = Path(put_tekst)
    if not put.exists():
        sys.exit(f"Nema datoteke s {sto}: {put}")
    tekst = put.read_text(encoding="utf-8").strip()
    if not tekst:
        sys.exit(f"Datoteka s {sto} je prazna: {put}")
    return tekst


def posalji(config: dict, kome: str, naslov: str, tijelo: str, prilog: Path = None):
    msg = EmailMessage()
    msg["Subject"] = naslov
    msg["From"] = config["zoho_email"]
    msg["To"] = kome
    msg.set_content(tijelo)

    if prilog is not None:
        tip, _ = mimetypes.guess_type(prilog.name)
        glavni, _, pod = (tip or "application/octet-stream").partition("/")
        msg.add_attachment(prilog.read_bytes(), maintype=glavni,
                           subtype=pod or "octet-stream", filename=prilog.name)

    def _posalji():
        posta.posalji(config, msg)

    with_retry(_posalji)


def main():
    parser = argparse.ArgumentParser(
        description="Pošalji jednu poruku jednom primatelju.")
    parser.add_argument("--kome", required=True, metavar="ADRESA")
    parser.add_argument("--naslov-datoteka", required=True, dest="naslov_datoteka")
    parser.add_argument("--tijelo-datoteka", required=True, dest="tijelo_datoteka")
    parser.add_argument("--prilog", help="Datoteka koja ide u prilogu")
    parser.add_argument("--stvarno", action="store_true",
                        help="Stvarno pošalji; bez ovoga se poruka samo ispiše")
    args = parser.parse_args()

    if "@" not in args.kome:
        sys.exit(f"Ovo ne izgleda kao adresa: {args.kome!r}")

    naslov = procitaj(args.naslov_datoteka, "naslovom")
    tijelo = procitaj(args.tijelo_datoteka, "tijelom poruke")
    prilog = Path(args.prilog) if args.prilog else None
    if prilog is not None and not prilog.exists():
        sys.exit(f"Nema priloga: {prilog}")

    print(f"Za:     {args.kome}")
    print(f"Naslov: {naslov}")
    if prilog:
        print(f"Prilog: {prilog.name}")
    print("--- poruka ---")
    print(tijelo)
    print("--- kraj ---")

    if not args.stvarno:
        print("\nPregled - ništa nije poslano. Za slanje dodaj --stvarno")
        return

    config = load_config()
    posalji(config, args.kome, naslov, tijelo, prilog)
    print(f"\nPoslano na {args.kome}.")

    # Jedan izvještaj tebi umjesto kopije same poruke: poruka je ovdje
    # cijela, pa trag ostaje, a u sandučiću ne izgleda kao da je upućena
    # polazniku.
    izvjestaj = [f"Poslano na {args.kome}.", ""]
    if prilog:
        izvjestaj.append(f"Prilog: {prilog.name}")
        izvjestaj.append("")
    izvjestaj += ["--- poruka ---", f"Naslov: {naslov}", "", tijelo]
    try:
        posta.javi(config, f"Poslano: {naslov}", "\n".join(izvjestaj))
    except Exception as e:
        print(f"[!] Poruka je poslana, ali izvještaj tebi nije: {e}")


if __name__ == "__main__":
    main()
