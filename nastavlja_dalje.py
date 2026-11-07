"""
Polaznik nastavlja na sljedeći modul - upiši ga i javi mu, bez nove prijave.

Tko je odradio Modul 1&2 i rekao da ide dalje nema se zašto ponovno
prijavljivati preko obrasca. Ovdje se njegovi podaci prepišu iz tablice
tečaja koji je završio u tablicu sljedećeg, i dobije istu potvrdu prijave
kakvu bi dobio da se prijavio sam.

Tablica sljedećeg tečaja mora već postojati. Ona nastane kad na taj tečaj
stigne prva prijava; dok je nema, nema se kamo upisati - skripta to javi i
ne radi ništa.

Nitko se ne upisuje dvaput: ako je ista adresa već u ciljnoj tablici,
polaznik je ondje i poruka se ne šalje ponovno.

Pokretanje:
    python3 nastavlja_dalje.py --tecaj "Modul 1&2 Split.xlsx" \\
        --email ana@primjer.hr --na "Modul 3 Split.xlsx"      # pregled
    python3 nastavlja_dalje.py ... --stvarno                   # upiši i javi

Pokreće ga tipka "Nastavlja dalje" uz polaznika na stranici tečaja.
"""

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

import tablice
from send_reminders import FIRST_PARTICIPANT_ROW, course_info, find_totals_row
from zoho_to_excel import (
    append_participant,
    load_config,
    send_confirmation_email,
    with_retry,
)

# Stupci u tablici polaznika, onako kako ih piše zoho_to_excel.
STUPCI = {
    "First name": 2,
    "Last Name": 3,
    "Street ": 4,
    "City/ Town ": 5,
    "Post/Zip Code ": 7,
    "Email Address": 8,
    "Mobile Ph": 9,
}


def nadji_tablicu(output_dir: Path, naziv: str) -> Path:
    for put in tablice.nadji(output_dir, javi=lambda _: None):
        if put.name == naziv:
            return put
    sys.exit(f"Nema tablice {naziv!r} u {output_dir}.")


def procitaj_polaznika(ws, adresa: str) -> dict:
    """Podaci polaznika iz tablice, u obliku kakav očekuje upis u novu."""
    trazena = adresa.strip().lower()
    for row in range(FIRST_PARTICIPANT_ROW, find_totals_row(ws)):
        u_retku = str(ws.cell(row=row, column=STUPCI["Email Address"]).value or "").strip()
        if u_retku.lower() != trazena:
            continue
        podaci = {}
        for kljuc, stupac in STUPCI.items():
            vrijednost = ws.cell(row=row, column=stupac).value
            podaci[kljuc] = "" if vrijednost is None else str(vrijednost).strip()
        return podaci
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Upiši polaznika na sljedeći modul i pošalji mu potvrdu.")
    parser.add_argument("--tecaj", required=True, metavar="NAZIV.xlsx",
                        help="Tablica tečaja s kojeg polaznik dolazi")
    parser.add_argument("--email", required=True, help="Adresa polaznika")
    parser.add_argument("--na", required=True, metavar="NAZIV.xlsx",
                        help="Tablica tečaja na koji se upisuje")
    parser.add_argument("--stvarno", action="store_true",
                        help="Stvarno upiši i pošalji; bez ovoga je pregled")
    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    odakle = nadji_tablicu(output_dir, args.tecaj)
    kamo = nadji_tablicu(output_dir, args.na)
    if odakle == kamo:
        sys.exit("Polaznik je već na tom tečaju - nema se kamo prepisati.")

    izvor = with_retry(lambda: load_workbook(odakle),
                       retry_on=(PermissionError, OSError))
    if "podaci" not in izvor.sheetnames:
        sys.exit(f"{odakle.name} nema list 'podaci'.")
    polaznik = procitaj_polaznika(izvor["podaci"], args.email)
    if polaznik is None:
        sys.exit(f"U {odakle.name} nema polaznika s adresom {args.email}.")

    cilj = with_retry(lambda: load_workbook(kamo),
                      retry_on=(PermissionError, OSError))
    if "podaci" not in cilj.sheetnames:
        sys.exit(f"{kamo.name} nema list 'podaci'.")
    ws = cilj["podaci"]
    info = course_info(ws, config)
    ime = f"{polaznik['First name']} {polaznik['Last Name']}".strip()

    print(f"{ime} <{polaznik['Email Address']}>")
    print(f"  s tečaja:  {odakle.name}")
    print(f"  na tečaj:  {info['course_code']} / {info['location']} "
          f"({info['dates']}) - {kamo.name}")

    if not args.stvarno:
        print("\nPregled - nije upisan i nije mu javljeno. "
              "Za upis dodaj --stvarno")
        return

    red = append_participant(ws, polaznik, find_totals_row(ws))
    if red is None:
        print(f"\n{ime} je već na popisu tog tečaja - ništa nije promijenjeno.")
        return

    with_retry(lambda: cilj.save(kamo), retry_on=(PermissionError, OSError))
    print(f"  upisan u redak {red}")

    # Ista potvrda kakvu dobije onaj tko se prijavi preko obrasca.
    if send_confirmation_email(config, polaznik, info["course_code"],
                               info["location"], info["dates"]):
        print(f"  potvrda poslana na {polaznik['Email Address']}")
    else:
        print("  [!] Potvrda nije poslana - provjeri 'odgovor na prijavu.docx' "
              "i adresu polaznika.")

    print("\nGotovo.")


if __name__ == "__main__":
    main()
