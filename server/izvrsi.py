"""
Izvrši zahtjev koji je stigao s web stranice.

Web stranica ne šalje mailove i ne dira tablice. Kad pritisneš tipku, ona
samo ostavi datoteku sa zahtjevom u ~/zahtjevi, a posao odradi ova skripta -
zaseban proces, s istim pravima kao cron poslovi i pod istom bravom.

Zašto tako, a ne da web sam pokrene posao: web je izložen proces. Ovako on
smije pisati samo u jednu mapu, i to datoteke koje se ovdje provjeravaju.
Ni da mu netko preotme vlast, ne može poslati mail polazniku ni promijeniti
tablicu - može samo zatražiti jedan od poslova s popisa ispod.

Pokreće je systemd čim se u mapi pojavi zahtjev (server/emmett-zahtjev.path),
pa je odziv na pritisak tipke trenutan.

Za ručnu provjeru:
    ~/venv/bin/python ~/Tgdgd/server/izvrsi.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

KORIJEN = Path(__file__).resolve().parent.parent
ZAHTJEVI = Path(os.environ.get("EMMETT_ZAHTJEVI", Path.home() / "zahtjevi"))
OBRADENO = ZAHTJEVI / "obradeno"
ISHODI = KORIJEN / "web" / "zahtjevi.json"
POKRENI = KORIJEN / "server" / "pokreni.sh"

# Koliko zadnjih ishoda se pamti za prikaz na stranici.
PAMTI = 20
# Koliko znakova ispisa se sprema uz ishod.
ISPIS_ZNAKOVA = 6000

# Jedini poslovi koji se smiju zatražiti. Sve ostalo se odbija.
# Vrijednost je funkcija koja od naziva tablice složi argumente.
POSLOVI = {
    "pregled_certifikata": lambda t: ["posalji_certifikate.py", "--tecaj", t],
    "posalji_certifikate": lambda t: ["posalji_certifikate.py", "--posalji",
                                      "--tecaj", t],
}


def sada() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ucitaj_ishode() -> list:
    if not ISHODI.exists():
        return []
    try:
        with open(ISHODI, encoding="utf-8") as f:
            podaci = json.load(f)
        return podaci if isinstance(podaci, list) else []
    except (ValueError, OSError):
        return []


def spremi_ishode(ishodi: list) -> None:
    """Piši preko privremene datoteke - web čita istu, ne smije uloviti
    polovičnu."""
    privremeno = ISHODI.with_suffix(".tmp")
    with open(privremeno, "w", encoding="utf-8") as f:
        json.dump(ishodi[-PAMTI:], f, ensure_ascii=False, indent=1)
    privremeno.replace(ISHODI)


def zabiljezi(ishod: dict) -> None:
    """Upiši ili osvježi ishod po njegovoj oznaci."""
    ishodi = [i for i in ucitaj_ishode() if i.get("oznaka") != ishod["oznaka"]]
    ishodi.append(ishod)
    ishodi.sort(key=lambda i: i.get("trazeno", ""))
    spremi_ishode(ishodi)


def poznate_tablice() -> set:
    """Nazivi tablica koje stvarno postoje. Zahtjev smije imenovati samo
    njih - naziv ide u naredbu, pa se ne uzima na vjeru."""
    sys.path.insert(0, str(KORIJEN))
    import tablice
    from zoho_to_excel import load_config
    mapa = Path(load_config()["output_dir"])
    return {p.name for p in tablice.nadji(mapa, javi=lambda _: None)}


def procitaj_zahtjev(put: Path):
    """(posao, tablica, trazio) ili (None, razlog, None)."""
    try:
        with open(put, encoding="utf-8") as f:
            zahtjev = json.load(f)
    except (ValueError, OSError) as e:
        return None, f"ne mogu pročitati zahtjev: {e}", None

    posao = zahtjev.get("posao")
    if posao not in POSLOVI:
        return None, f"nepoznat posao {posao!r}", None

    tablica = zahtjev.get("tablica", "")
    if tablica not in poznate_tablice():
        return None, f"nema tablice {tablica!r}", None

    return posao, tablica, zahtjev.get("trazio", "?")


def odradi(put: Path) -> None:
    oznaka = put.stem
    posao, tablica, trazio = procitaj_zahtjev(put)

    if posao is None:
        razlog = tablica   # kod greške drugi član nosi objašnjenje
        print(f"[!] {put.name}: {razlog}")
        zabiljezi({"oznaka": oznaka, "posao": "?", "tablica": "",
                   "trazio": "?", "trazeno": sada(), "gotovo": sada(),
                   "status": "odbijeno", "ispis": razlog})
        put.unlink(missing_ok=True)
        return

    # makni zahtjev prije pokretanja: ako posao padne usred, ne pokreće se
    # ponovno sam od sebe
    OBRADENO.mkdir(parents=True, exist_ok=True)
    arhiva = OBRADENO / put.name
    put.replace(arhiva)

    osnova = {"oznaka": oznaka, "posao": posao, "tablica": tablica,
              "trazio": trazio, "trazeno": sada()}
    zabiljezi(dict(osnova, status="u tijeku", ispis=""))
    print(f"=== {sada()} {posao} / {tablica} (tražio {trazio}) ===")

    naredba = [str(POKRENI), *POSLOVI[posao](tablica)]
    try:
        rezultat = subprocess.run(naredba, capture_output=True, text=True,
                                  timeout=3600)
        ispis = (rezultat.stdout or "") + (rezultat.stderr or "")
        status = "gotovo" if rezultat.returncode == 0 else "greška"
    except subprocess.TimeoutExpired:
        ispis, status = "Posao traje predugo pa je prekinut.", "greška"
    except OSError as e:
        ispis, status = f"Ne mogu pokrenuti posao: {e}", "greška"

    print(ispis.rstrip())
    zabiljezi(dict(osnova, gotovo=sada(), status=status,
                   ispis=ispis[-ISPIS_ZNAKOVA:].strip()))

    # nakon slanja je snimka zastarjela - osvježi je da stranica odmah
    # pokaže novo stanje
    subprocess.run([str(POKRENI), "web/skupi.py"],
                   capture_output=True, text=True, timeout=1800)


def main():
    ZAHTJEVI.mkdir(parents=True, exist_ok=True)
    # Petlja, a ne jedan prolaz: ako zahtjev stigne dok ovaj posao traje,
    # systemd ga možda neće ponovno pokrenuti - mapa nikad nije bila prazna.
    while True:
        cekaju = sorted(p for p in ZAHTJEVI.glob("*.json") if p.is_file())
        if not cekaju:
            return
        for put in cekaju:
            odradi(put)


if __name__ == "__main__":
    main()
