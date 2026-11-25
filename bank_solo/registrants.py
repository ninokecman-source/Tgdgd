"""
Čita popis polaznika iz Excel tablica tečajeva (generiranih zoho_to_excel.py)
radi povezivanja bankovnih uplata s pravom osobom, i radi upisivanja
uplaćenog iznosa natrag u tablicu.
"""

import unicodedata
from pathlib import Path

from openpyxl import load_workbook

FIRST_PARTICIPANT_ROW = 10


def strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_name(text: str) -> str:
    return strip_diacritics(text).upper().strip()


def _tablice_u(excel_dir: Path) -> list:
    """Tablice koje se smiju čitati. Ista pravila kao u glavnim skriptama
    (preskače trag datoteke u oblaku i kopiju s sukobom) - ovdje je to
    najvažnije, jer bi uplata upisana u krivu kopiju otišla u prazno."""
    try:
        from mailer import iz_glavnog_foldera
        modul = iz_glavnog_foldera("tablice")
    except Exception:
        modul = None

    if modul is None:
        return sorted(p for p in excel_dir.glob("*.xlsx")
                      if not p.name.startswith("~$"))
    return modul.nadji(excel_dir)


def load_registrants(excel_dir: Path) -> list:
    """Vrati listu dictova za svakog polaznika u svim .xlsx datotekama u
    excel_dir (osim predloška): {first_name, last_name, name_variants,
    email, course_code, location, dates, file_path, row}."""
    registrants = []

    for path in _tablice_u(Path(excel_dir)):
        try:
            wb = load_workbook(path)
        except Exception:
            continue
        if "podaci" not in wb.sheetnames:
            continue
        ws = wb["podaci"]

        course_code = ws["C4"].value or ""
        location = ws["C5"].value or ""
        dates = ws["C6"].value or ""

        row = FIRST_PARTICIPANT_ROW
        while True:
            first_name = ws.cell(row=row, column=2).value
            last_name = ws.cell(row=row, column=3).value
            row_number = ws.cell(row=row, column=1).value
            if row_number is None:
                break  # izvan tablice polaznika (stigli do reda ukupnog iznosa)

            if first_name:
                full = f"{first_name} {last_name or ''}".strip()
                reversed_name = f"{last_name or ''} {first_name}".strip()
                street = ws.cell(row=row, column=4).value or ""
                city = ws.cell(row=row, column=5).value or ""
                postal_code = ws.cell(row=row, column=7).value or ""
                address = f"{street}, {postal_code} {city}".strip(", ")
                registrants.append({
                    "first_name": str(first_name).strip(),
                    "last_name": str(last_name or "").strip(),
                    "name_variants": [normalize_name(full), normalize_name(reversed_name)],
                    "email": ws.cell(row=row, column=8).value or "",
                    "address": address,
                    "course_code": course_code,
                    "location": location,
                    "dates": str(dates).strip(),
                    "file_path": path,
                    "row": row,
                })
            row += 1

    return registrants


def find_matching_registrant(raw_line: str, registrants: list):
    """Traži bilo koju poznatu varijantu imena polaznika kao podniz u
    (normaliziranom) tekstu retka transakcije. Vraća prvi pronađeni
    registrant dict, ili None.

    Zadržano radi jednostavnih provjera; za pravo uparivanje uplate koristi
    match_payment(), koji zna razlikovati uplatitelja od polaznika."""
    pronadjeni = find_registrants_in(raw_line, registrants)
    return pronadjeni[0] if pronadjeni else None


def find_registrants_in(text: str, registrants: list) -> list:
    """Svi polaznici čije se ime pojavljuje u tekstu, bez ponavljanja."""
    if not text:
        return []
    normalized = normalize_name(text)
    pronadjeni = []
    for registrant in registrants:
        for variant in registrant["name_variants"]:
            if variant and variant in normalized:
                pronadjeni.append(registrant)
                break
    return pronadjeni


def _oznaka(registrant) -> str:
    return f"{registrant['first_name']} {registrant['last_name']}".strip()


def _po_tecaju(kandidati: list, description: str):
    """Isti čovjek upisan na više tečajeva - odluči po kodu tečaja iz opisa.

    Polaznik koji sluša Modul 4 i Modul 5 u popisu je dvaput, kao dva
    zapisa. Kad uplatu šalje on sam, i ime uplatitelja i opis pokazuju na
    oba, pa pitanje nije TKO nego NA KOJI TEČAJ - a to u opisu obično i
    piše ('Tečaj Emmett tehnike Modul 4').

    Vrati zapis samo ako opis imenuje točno jedan od tih tečajeva; dva
    Modula 4 u dva grada ostaju za ručnu provjeru, kao i dosad."""
    if len({_oznaka(r) for r in kandidati}) != 1:
        return None   # nisu ista osoba, pa kod tečaja ništa ne rješava
    opis = normalize_name(description)
    pogodci = [r for r in kandidati
               if r.get("course_code")
               and normalize_name(r["course_code"]) in opis]
    return pogodci[0] if len(pogodci) == 1 else None


def _neodluceno(zapisi: list, gdje: str) -> str:
    """Zašto se nije moglo odlučiti. Razlikuje dva slučaja koja su se prije
    oba javljala kao 'više polaznika' - pa je uz uplatu jednog čovjeka
    pisalo da ih je više, i to s jednim imenom u zagradi."""
    imena = sorted({_oznaka(r) for r in zapisi})
    if len(imena) == 1:
        # S mjestom, jer dva puta isti kod u dva grada su upravo slučaj u
        # kojem kod tečaja iz opisa ništa ne razrješava.
        tecajevi = ", ".join(sorted({
            " ".join(filter(None, [r.get("course_code") or "?", r.get("location")]))
            for r in zapisi}))
        return (f"{imena[0]} je upisan na više tečajeva ({tecajevi}), a iz "
                f"opisa se ne vidi na koji se uplata odnosi")
    return (f"{gdje} odgovara većem broju polaznika ({', '.join(imena)}) i "
            f"ne mogu odlučiti za koga je uplata")


def match_payment(name: str, description: str, registrants: list):
    """Odluči na čije ime ide uplata. Vrati (registrant, upozorenje);
    registrant je None ako se ne može pouzdano odlučiti.

    Ljudi plaćaju i za druge - roditelj za dijete, kolegica za kolegicu -
    pa ime uplatitelja nije nužno ime polaznika. Zato je OPIS PLAĆANJA
    mjerodavan: tamo se piše za koga se plaća. Ime uplatitelja je rezerva,
    za uobičajen slučaj kad netko plaća sam za sebe.

    Prije se pretraživalo ime i opis zajedno i uzimalo prvo pronađeno ime,
    redom kojim su polaznici u tablicama - pa je uplatitelj koji je i sam
    polaznik uvijek pobjeđivao osobu za koju plaća, i novac bi se upisao
    krivom čovjeku."""
    u_opisu = find_registrants_in(description, registrants)
    u_imenu = find_registrants_in(name, registrants)
    kljuc = lambda r: (str(r["file_path"]), r["row"])
    iz_imena = {kljuc(r) for r in u_imenu}

    if len(u_opisu) == 1:
        polaznik = u_opisu[0]
        if iz_imena and kljuc(polaznik) not in iz_imena:
            return polaznik, (f"uplatitelj je {name.strip()}, a plaćeno je za "
                              f"{_oznaka(polaznik)} - knjižim na polaznika iz opisa")
        return polaznik, ""

    if len(u_opisu) > 1:
        # Opis spominje više poznatih imena (npr. "uplata za X, uplatitelj Y").
        # Uplatitelj je već poznat iz svog polja, pa ostaje onaj drugi.
        kandidati = [r for r in u_opisu if kljuc(r) not in iz_imena]
        if len(kandidati) == 1:
            return kandidati[0], (f"opis spominje više polaznika, uzimam "
                                  f"{_oznaka(kandidati[0])} (uplatitelj je "
                                  f"{name.strip()})")
        # Kandidati su prazni kad uplatitelj plaća sam za sebe: tada je on
        # i u imenu i u opisu, pa ga oduzimanje ukloni. Tu se gleda cijeli
        # popis iz opisa.
        jedan = _po_tecaju(kandidati or u_opisu, description)
        if jedan is not None:
            return jedan, (f"{_oznaka(jedan)} je upisan na više tečajeva - "
                           f"knjižim na {jedan['course_code']}, kako piše u opisu")
        return None, _neodluceno(u_opisu, "opis")

    if len(u_imenu) == 1:
        return u_imenu[0], ""

    if len(u_imenu) > 1:
        jedan = _po_tecaju(u_imenu, description)
        if jedan is not None:
            return jedan, (f"{_oznaka(jedan)} je upisan na više tečajeva - "
                           f"knjižim na {jedan['course_code']}, kako piše u opisu")
        return None, _neodluceno(u_imenu, "ime uplatitelja")

    return None, ""


def add_payment(file_path: Path, row: int, amount: float) -> float:
    """Doda amount na postojeću vrijednost u koloni 'Payment Received' (L)
    za taj red (akumulira ako već postoji npr. akontacija). Vrati novi
    ukupni iznos."""
    wb = load_workbook(file_path)
    ws = wb["podaci"]
    cell = ws.cell(row=row, column=12)
    existing = cell.value or 0
    try:
        existing = float(existing)
    except (TypeError, ValueError):
        existing = 0
    new_total = existing + amount
    cell.value = new_total
    wb.save(file_path)
    return new_total
