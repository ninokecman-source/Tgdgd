"""
Skupi sve što web pregled prikazuje u jednu datoteku: web/stanje.json.

Zašto snimka, a ne čitanje tablica pri svakom otvaranju stranice:

  1. Tablice su u Dropboxu i u njih pišu cron poslovi. Čitanje usred pisanja
     ili usred rclone sinkronizacije moglo bi dati polovičan podatak.
     Ovaj se posao pokreće kroz pokreni.sh, pod istom bravom kao i ostali,
     pa se s njima nikad ne preklapa.
  2. Otvaranje petnaest Excel tablica traje nekoliko sekundi. Na mobitelu,
     pri svakom osvježavanju stranice, to bi bilo neupotrebljivo.

Web aplikacija (web/app.py) zato samo čita ovu datoteku i nikad ne dira
tablice. Ako snimka zastari, stranica to javlja na vrhu.

Pokretanje (uvijek kroz pokreni.sh, da povuče svježe tablice iz Dropboxa):

    ~/Tgdgd/server/pokreni.sh web/skupi.py
"""

import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

KORIJEN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KORIJEN))

from openpyxl import load_workbook

import pozivi
import predlosci
import tablice
from provjeri_logove import DEFAULT_LOGS, PROBLEM_UZORCI
from send_reminders import (
    COL_EMAIL,
    COL_FIRST_NAME,
    COL_LAST_NAME,
    course_info,
    datum_rijecima,
    iznosi_tecaja,
    parse_course_dates,
)
from zoho_to_excel import FIRST_PARTICIPANT_ROW, find_totals_row, load_config, with_retry

SNIMKA = Path(__file__).with_name("stanje.json")

COL_MOBITEL = 9
COL_NOVI_ILI_PONOVNI = 11
COL_UPLATA = 12
COL_BILJESKA = 13

# Koliko zadnjih bajtova loga se pregledava za greške i prolaze. Logovi rastu
# polako, pa je ovo i tako povijest od nekoliko mjeseci.
LOG_REP = 300_000

# Zaglavlje koje pokreni.sh upiše prije svakog posla:
#   === 2026-10-14 12:57:48 posalji_certifikate.py  ===
ZAGLAVLJE = re.compile(r"^=== (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.+?)\s*===$")


def oznaka(tekst: str) -> str:
    """'Modul 1&2 Split.xlsx' -> 'modul-1-2-split' (za adresu stranice)."""
    tekst = predlosci.bez_dijakritika(tekst.lower())
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", tekst)).strip("-")


def broj(vrijednost) -> float:
    """Uplata iz tablice u broj. Ručno upisano '100 eur' ili '100,00' se
    također prihvaća - tablicu ispunjava čovjek, ne samo skripta."""
    if vrijednost is None or vrijednost == "":
        return 0.0
    if isinstance(vrijednost, (int, float)):
        return float(vrijednost)
    tekst = str(vrijednost).replace(",", ".")
    nadjeno = re.search(r"-?\d+(?:\.\d+)?", tekst)
    return float(nadjeno.group()) if nadjeno else 0.0


def tekst(vrijednost) -> str:
    return "" if vrijednost is None else str(vrijednost).strip()


def citaj_tecaj(put: Path, config: dict, danas: date) -> dict:
    wb = with_retry(lambda: load_workbook(put, data_only=True),
                    retry_on=(PermissionError, OSError))
    if "podaci" not in wb.sheetnames:
        return None
    ws = wb["podaci"]

    info = course_info(ws, config)
    pocetak, kraj = parse_course_dates(info["dates"])
    cijena = broj(iznosi_tecaja(config, info["course_code"])["cijena"])

    polaznici = []
    totals_row = find_totals_row(ws)
    for row in range(FIRST_PARTICIPANT_ROW, totals_row):
        ime = tekst(ws.cell(row=row, column=COL_FIRST_NAME).value)
        prezime = tekst(ws.cell(row=row, column=COL_LAST_NAME).value)
        if not ime and not prezime:
            continue
        uplaceno = broj(ws.cell(row=row, column=COL_UPLATA).value)
        polaznici.append({
            "ime": f"{ime} {prezime}".strip(),
            "email": tekst(ws.cell(row=row, column=COL_EMAIL).value),
            "mobitel": tekst(ws.cell(row=row, column=COL_MOBITEL).value),
            "nr": tekst(ws.cell(row=row, column=COL_NOVI_ILI_PONOVNI).value),
            "uplaceno": uplaceno,
            "manjka": round(cijena - uplaceno, 2) if cijena else 0.0,
            "biljeska": tekst(ws.cell(row=row, column=COL_BILJESKA).value),
        })

    if kraj and kraj < danas:
        stanje = "prosao"
    elif pocetak and pocetak <= danas:
        stanje = "u toku"
    else:
        stanje = "dolazi"

    # prvi dan i rok uplate stoje ovdje, a ne se računaju na stranici: web
    # čita samo ovu snimku, pa sve što mu treba mora biti u njoj
    rok = (pocetak - timedelta(days=config.get("payment_due_days_before", 7))
           if pocetak else None)

    return {
        "oznaka": oznaka(put.stem),
        "datoteka": put.name,
        "kod": info["course_code"],
        "mjesto": info["location"],
        "datumi": info["dates"],
        "instruktor": info["instructor_name"],
        "prvi_dan": datum_rijecima(pocetak) if pocetak else "",
        "rok_uplate": rok.strftime("%d.%m.%Y.") if rok else "",
        "pocetak": pocetak.isoformat() if pocetak else None,
        "kraj": kraj.isoformat() if kraj else None,
        "stanje": stanje,
        "dana_do": (pocetak - danas).days if pocetak else None,
        "polaznika": len(polaznici),
        "uplaceno": round(sum(p["uplaceno"] for p in polaznici), 2),
        "cijena": cijena,
        "duznika": sum(1 for p in polaznici if p["manjka"] > 0) if cijena else 0,
        "polaznici": polaznici,
    }


def citaj_json(put: Path):
    if not put.exists():
        return {}
    try:
        with open(put, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def citaj_slanja() -> dict:
    """Što je koja skripta zadnje poslala - iz njihovih datoteka stanja."""
    podsjetnici = {}
    for kljuc, adrese in citaj_json(KORIJEN / "sent_reminders.json").items():
        datoteka, _, dana = kljuc.partition("::")
        podsjetnici.setdefault(datoteka, []).append(
            {"dana_prije": dana, "adresa": len(adrese)})
    for popis in podsjetnici.values():
        popis.sort(key=lambda r: -int(r["dana_prije"] or 0))

    return {
        "podsjetnici": podsjetnici,
        "tablice": citaj_json(KORIJEN / "sent_reports.json"),
        "certifikati_napravljeni": citaj_json(KORIJEN / "napravljeni_certifikati.json"),
        "certifikati_poslani": citaj_json(KORIJEN / "poslani_certifikati.json"),
        "obradenih_mailova": len(citaj_json(KORIJEN / "processed_uids.json") or []),
    }


def put_baze(config_banka: dict) -> Path:
    """state_db_path je u config.json zapisan relativno - sync.py se pokreće
    iz korijena repozitorija, pa se i ovdje tako tumači."""
    zadano = config_banka.get("state_db_path", "bank_solo_state.sqlite3")
    put = Path(zadano)
    if put.is_absolute():
        return put
    uz_korijen = KORIJEN / put
    return uz_korijen if uz_korijen.exists() else KORIJEN / "bank_solo" / put


def citaj_uplate() -> dict:
    """Proknjižene uplate iz baze bankovne skripte."""
    config_banka = citaj_json(KORIJEN / "bank_solo" / "config.json")
    baza = put_baze(config_banka)
    if not baza.exists():
        return {"baza": str(baza), "ima": False}

    # samo za čitanje - web ne smije dirati stanje bankovne skripte
    veza = sqlite3.connect(f"file:{baza}?mode=ro", uri=True)
    try:
        ukupno, broj_uplata = veza.execute(
            "SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM processed_transactions"
        ).fetchone()
        zadnje = [
            {"ime": r[0], "iznos": r[1], "ponuda": r[2], "kada": r[3]}
            for r in veza.execute(
                "SELECT matched_name, amount, solo_ponuda, processed_at "
                "FROM processed_transactions ORDER BY processed_at DESC, rowid DESC "
                "LIMIT 20")
        ]
        nepovezane = citaj_nepovezane(veza)
    finally:
        veza.close()

    return {"baza": str(baza), "ima": True, "ukupno": round(ukupno or 0, 2),
            "broj": broj_uplata, "zadnje": zadnje, "nepovezane": nepovezane}


def citaj_nepovezane(veza) -> list:
    """Uplate koje čekaju da im se kaže čije su. Tablica je novija od baze,
    pa se njezino postojanje provjerava - stara baza nije greška."""
    ima = veza.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='unmatched_transactions'").fetchone()
    if not ima:
        return []
    return [
        {"ref": r[0], "datum": r[1], "iznos": r[2], "uplatitelj": r[3],
         "opis": r[4], "razlog": r[5], "primijeceno": r[6]}
        for r in veza.execute(
            "SELECT ref_id, date, amount, name, description, razlog, seen_at "
            "FROM unmatched_transactions WHERE resolved_at IS NULL "
            "ORDER BY seen_at DESC, rowid DESC")
    ]


def repa_loga(put: Path) -> list:
    """Zadnjih LOG_REP bajtova loga, u retke. Čita se u bajtovima pa dekodira
    jer rez može pasti usred kvačice."""
    with open(put, "rb") as f:
        f.seek(max(0, put.stat().st_size - LOG_REP))
        sadrzaj = f.read()
    return sadrzaj.decode("utf-8", errors="replace").splitlines()


def citaj_logove(config: dict) -> dict:
    """Greške i prolazi iz logova. Svakoj se grešci pridruži posao u kojem se
    pojavila - zaglavlje koje pokreni.sh upiše prije svakog pokretanja."""
    greske, stanje_logova = [], []
    # Prolazi se grupiraju po poslu, ne nabrajaju redom: prijave se citaju
    # svakih pola sata, pa bi inace 48 istih redaka dnevno zatrpalo sve
    # ostalo. Zanima te kad je posao zadnji put prosao, ne svaki put.
    prolazi = {}

    for naziv, put_tekst in config.get("watch_logs", DEFAULT_LOGS).items():
        put = Path(put_tekst).expanduser()
        if not put.exists():
            stanje_logova.append({"naziv": naziv, "put": str(put), "ima": False})
            continue

        podaci = put.stat()
        stanje_logova.append({
            "naziv": naziv,
            "put": str(put),
            "ima": True,
            "zadnja_izmjena": datetime.fromtimestamp(podaci.st_mtime).isoformat(timespec="seconds"),
            "velicina": podaci.st_size,
        })

        kada, posao = "", ""
        for redak in repa_loga(put):
            zaglavlje = ZAGLAVLJE.match(redak.strip())
            if zaglavlje:
                kada, posao = zaglavlje.group(1), zaglavlje.group(2)
                unos = prolazi.setdefault((naziv, posao),
                                          {"log": naziv, "posao": posao,
                                           "kada": kada, "broj": 0})
                unos["broj"] += 1
                unos["kada"] = max(unos["kada"], kada)
                continue
            if redak.strip() and any(u.search(redak) for u in PROBLEM_UZORCI):
                greske.append({"log": naziv, "kada": kada, "posao": posao,
                               "redak": redak.strip()[:400]})

    redom = sorted(prolazi.values(), key=lambda r: r["kada"], reverse=True)
    greske.sort(key=lambda r: r["kada"], reverse=True)
    return {"greske": greske[:60], "prolazi": redom, "logovi": stanje_logova}


def main():
    config = load_config()
    output_dir = Path(config["output_dir"])
    danas = date.today()
    upozorenja = []

    if not output_dir.exists():
        upozorenja.append(f"Ne postoji folder s tablicama: {output_dir}")
        datoteke = []
    else:
        datoteke = tablice.nadji(output_dir, javi=upozorenja.append)

    tecajevi = []
    for put in datoteke:
        try:
            tecaj = citaj_tecaj(put, config, danas)
        except Exception as e:
            upozorenja.append(f"[!] {put.name}: ne mogu pročitati tablicu ({e})")
            continue
        if tecaj is None:
            upozorenja.append(f"[!] {put.name}: nema list 'podaci', preskočeno")
            continue
        tecajevi.append(tecaj)

    tecajevi.sort(key=lambda t: (t["pocetak"] or "9999"), reverse=True)

    # Koga se može pozvati s prethodnog modula. Računa se ovdje, uz sve
    # tečajeve na okupu, jer web čita samo ovu snimku - i jer je ovo jedino
    # mjesto gdje su svi polaznici svih tečajeva već pročitani.
    poslani = citaj_json(KORIJEN / "poslani_pozivi.json")
    for tecaj in tecajevi:
        vec = poslani.get(tecaj["datoteka"], {}).get("poslano", [])
        tecaj["pozvati"] = pozivi.kandidati(tecaj, tecajevi, config, vec)
        tecaj["pozvano"] = len(vec)

    stanje = {
        "snimljeno": datetime.now().isoformat(timespec="seconds"),
        "folder": str(output_dir),
        "tecajevi": tecajevi,
        "slanja": citaj_slanja(),
        "uplate": citaj_uplate(),
        "upozorenja": upozorenja,
    }
    stanje.update(citaj_logove(config))

    # piši preko privremene datoteke, da web nikad ne pročita polovičnu snimku
    privremeno = SNIMKA.with_suffix(".tmp")
    with open(privremeno, "w", encoding="utf-8") as f:
        json.dump(stanje, f, ensure_ascii=False, indent=1, sort_keys=True)
    privremeno.replace(SNIMKA)

    print(f"Snimka: {len(tecajevi)} tečajeva, {len(stanje['greske'])} grešaka "
          f"u logovima -> {SNIMKA}")
    for poruka in upozorenja:
        print(f"  {poruka}")


if __name__ == "__main__":
    main()
