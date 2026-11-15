"""
Upiši uplatu koja nije stigla preko banke.

Za gotovinu i za kompenzaciju (polaznik ustupi prostor umjesto da plati).
Takav polaznik inače zauvijek stoji kao dužnik: izvod ga nikad neće pokriti,
podsjetnik mu odlazi bez razloga, a iznos visi na stranici Uplate.

S --podmiri se upiše točno onoliko koliko mu nedostaje do cijene tečaja, a
koliko to jest čita se iz tablice u tom trenutku. Tipka na stranici radi
tako: iznos ne putuje s njom, pa se ne može dogoditi da stranica pokazuje
staro stanje i upiše preveliku uplatu.

Iznos se DODAJE na ono što u tablici već piše, isto kao kad se uplata knjiži
iz izvoda - tko je platio akontaciju pa ostatak u gotovini, ima zbroj. Uz to
se u bilješku (stupac M) upiše čime je plaćeno, koliko i kada, jer u izvodu
toga nema pa se poslije ne bi imalo po čemu provjeriti.

Svaka takva uplata ide i u 'rucne_uplate.json'. To je jedini novac u sustavu
koji nema potvrdu izvan tablice, pa neka bar ima svoj trag.

Pokretanje:
    python3 upisi_uplatu.py --tablica "Modul 3 Zadar.xlsx" \\
        --email ana@primjer.hr --podmiri                   # samo pokaži
    python3 upisi_uplatu.py --tablica "..." --email ... --podmiri --stvarno
    python3 upisi_uplatu.py --tablica "..." --ime "Ana Anić" --iznos 50 \\
        --nacin gotovina --stvarno                         # djelomična uplata
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

import tablice
# nadji_red zna pravilo koje vrijedi i ovdje: adresa ima prednost, a na dva
# pogotka se tablica ne dira nego se traži da to čovjek razriješi.
from otkazi_polaznika import nadji_red, nadji_tablicu
from send_reminders import course_info, iznosi_tecaja
from zoho_to_excel import find_totals_row, load_config, with_retry

import prava

COL_UPLATA = 12
COL_BILJESKA = 13
ZAPISNIK = Path(__file__).with_name("rucne_uplate.json")

# Što piše u bilješci kad se ne kaže drugačije. Mora pisati nešto: u izvodu
# ove uplate nema, pa bi inače za godinu dana stajao iznos bez ikakvog traga
# odakle je.
ZADANI_NACIN = "uplaćeno izvan banke"

# Iznad ovoga je gotovo sigurno zalutala decimalna točka, a ne uplata.
NAJVISE = 100000


def broj(vrijednost) -> float:
    if vrijednost is None or vrijednost == "":
        return 0.0
    if isinstance(vrijednost, (int, float)):
        return float(vrijednost)
    tekst = str(vrijednost).replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return float(tekst)
    except ValueError:
        return 0.0


def zabiljezi(podaci: dict) -> None:
    zapisi = []
    if ZAPISNIK.exists():
        try:
            with open(ZAPISNIK, encoding="utf-8") as f:
                zapisi = json.load(f)
        except (ValueError, OSError):
            zapisi = []
    if not isinstance(zapisi, list):
        zapisi = []
    zapisi.append(podaci)
    with open(ZAPISNIK, "w", encoding="utf-8") as f:
        json.dump(zapisi, f, ensure_ascii=False, indent=1)
    prava.zakljucaj(ZAPISNIK)


def iznos_rijecima(iznos: float) -> str:
    return f"{iznos:.2f}".replace(".", ",") + " €"


def upisi(put: Path, config: dict, email: str, ime: str, iznos, nacin: str,
          stvarno: bool) -> int:
    """iznos je broj, ili None za 'koliko god mu nedostaje do cijene'."""
    wb = with_retry(lambda: load_workbook(put), retry_on=(PermissionError, OSError))
    if "podaci" not in wb.sheetnames:
        sys.exit(f"{put.name} nema list 'podaci'.")
    ws = wb["podaci"]

    totals_row = find_totals_row(ws)
    red, puno_ime, adresa = nadji_red(ws, totals_row, email, ime)

    prije = broj(ws.cell(row=red, column=COL_UPLATA).value)

    if iznos is None:
        cijena = broj(iznosi_tecaja(config, course_info(ws, config)["course_code"])["cijena"])
        if not cijena:
            sys.exit("Cijena tečaja nije podešena (price_total u config.json), "
                     "pa ne znam koliko mu nedostaje. Upiši iznos s --iznos.")
        iznos = round(cijena - prije, 2)
        if iznos <= 0:
            print(f"{puno_ime} nema duga - uplaćeno {iznos_rijecima(prije)} "
                  f"od {iznos_rijecima(cijena)}. Ne diram tablicu.")
            return 0

    poslije = round(prije + iznos, 2)
    stara_biljeska = str(ws.cell(row=red, column=COL_BILJESKA).value or "").strip()
    danas = datetime.now()
    nova = f"{nacin}: {iznos_rijecima(iznos)} ({danas:%d.%m.%Y.})"
    biljeska = f"{stara_biljeska}; {nova}" if stara_biljeska else nova

    tecaj = f"{ws['C4'].value or ''} / {ws['C5'].value or ''}".strip(" /")
    print(f"{put.name} ({tecaj})")
    print(f"  redak {red}: {puno_ime}" + (f" <{adresa}>" if adresa else " (bez adrese)"))
    print(f"  uplaćeno: {iznos_rijecima(prije)} -> {iznos_rijecima(poslije)}")
    print(f"  bilješka: {biljeska}")

    if not stvarno:
        print("\nPregled - ništa nije promijenjeno. Za upis dodaj --stvarno")
        return 0

    ws.cell(row=red, column=COL_UPLATA, value=poslije)
    ws.cell(row=red, column=COL_BILJESKA, value=biljeska)
    wb.save(put)

    zabiljezi({
        "kada": danas.isoformat(timespec="seconds"),
        "tablica": put.name,
        "tecaj": tecaj,
        "ime": puno_ime,
        "email": adresa,
        "iznos": iznos,
        "nacin": nacin,
        "uplaceno_poslije": poslije,
    })
    print(f"\nUpisano. {puno_ime} sada ima {iznos_rijecima(poslije)}.")
    return 1


def main():
    parser = argparse.ArgumentParser(
        description="Upiše uplatu koja nije prošla kroz banku (gotovina, kompenzacija).")
    parser.add_argument("--tablica", required=True, metavar="NAZIV.xlsx")
    parser.add_argument("--email", default="", help="Adresa polaznika")
    parser.add_argument("--ime", default="", help="Ime i prezime, za polaznika bez adrese")
    koliko = parser.add_mutually_exclusive_group(required=True)
    koliko.add_argument("--iznos", help="Koliko je uplaćeno, u eurima")
    koliko.add_argument("--podmiri", action="store_true",
                        help="Upiši točno onoliko koliko mu nedostaje do cijene")
    parser.add_argument("--nacin", default=ZADANI_NACIN,
                        help=f"Čime je plaćeno; zadano {ZADANI_NACIN!r}")
    parser.add_argument("--stvarno", action="store_true",
                        help="Bez ovoga se samo prikaže što bi se upisalo")
    args = parser.parse_args()

    if not args.email and not args.ime:
        sys.exit("Treba --email ili --ime.")
    iznos = None
    if args.iznos is not None:
        iznos = round(broj(args.iznos), 2)
        if iznos <= 0:
            sys.exit(f"Iznos mora biti veći od nule: {args.iznos!r}")
        if iznos > NAJVISE:
            sys.exit(f"Iznos {args.iznos!r} je prevelik za uplatu polaznika - "
                     f"provjeri decimalnu točku.")
    nacin = " ".join(args.nacin.split())
    if not nacin:
        sys.exit("--nacin ne smije biti prazan: u izvodu ove uplate nema, pa "
                 "u tablici mora pisati čime je plaćena.")

    config = load_config()
    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    # Sve što ne valja već je izašlo kroz sys.exit s objašnjenjem, pa je
    # dolazak dovde uspjeh - i kod pregleda i kod upisa.
    put = nadji_tablicu(output_dir, args.tablica)
    upisi(put, config, args.email, args.ime, iznos, nacin, args.stvarno)
    return 0


if __name__ == "__main__":
    sys.exit(main())
