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
import re
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

# Najveća dopuštena duljina teksta koji stigne sa stranice.
NAJDULJI_NASLOV = 300
NAJDULJE_TIJELO = 20000
NAJDULJE_IME = 120
# Jedan tečaj ima najviše dvadesetak ljudi; stotinu je već znak da nešto
# nije u redu, pa se takav zahtjev odbija umjesto da se izvrši.
NAJVISE_PRIMATELJA = 100


class Odbijeno(Exception):
    """Zahtjev ne valja - ne pokreće se ništa."""


def provjeri_adresu(zahtjev: dict) -> str:
    adresa = str(zahtjev.get("email", "")).strip()
    if "@" not in adresa or len(adresa.split()) != 1:
        raise Odbijeno(f"ovo ne izgleda kao adresa: {adresa!r}")
    return adresa


def provjeri_tekst(zahtjev: dict) -> tuple:
    naslov = str(zahtjev.get("naslov", "")).strip()
    tijelo = str(zahtjev.get("tijelo", "")).strip()
    if not naslov or not tijelo:
        raise Odbijeno("poruka nema naslov ili tijelo")
    if len(naslov) > NAJDULJI_NASLOV or len(tijelo) > NAJDULJE_TIJELO:
        raise Odbijeno("poruka je predugačka")
    if "\n" in naslov or "\r" in naslov:
        raise Odbijeno("naslov ne smije imati prijelom retka")
    return naslov, tijelo


def zapisi_tekst(mapa: Path, zahtjev: dict) -> tuple:
    """Naslov i tijelo u datoteke uz zahtjev. Tekst ide datotekama, a ne
    argumentima naredbe: duga poruka ne stane u naredbu, a ovako ni navodnik
    ni novi red ne mogu ništa pokvariti. Usput ostaje i trag što je poslano."""
    naslov, tijelo = provjeri_tekst(zahtjev)
    mapa.mkdir(parents=True, exist_ok=True)
    (mapa / "naslov.txt").write_text(naslov, encoding="utf-8")
    (mapa / "tijelo.txt").write_text(tijelo, encoding="utf-8")
    return str(mapa / "naslov.txt"), str(mapa / "tijelo.txt")


def _certifikati(posalji: bool):
    def sastavi(zahtjev, tablica, mapa):
        naredba = ["posalji_certifikate.py", "--tecaj", tablica]
        if posalji:
            naredba.append("--posalji")
        if zahtjev.get("naslov") or zahtjev.get("tijelo"):
            naslov_put, tijelo_put = zapisi_tekst(mapa, zahtjev)
            naredba += ["--naslov-datoteka", naslov_put,
                        "--tijelo-datoteka", tijelo_put]
        return naredba
    return sastavi


def _podsjetnik(zahtjev, tablica, mapa):
    adresa = provjeri_adresu(zahtjev)
    naslov_put, tijelo_put = zapisi_tekst(mapa, zahtjev)
    return ["posalji_poruku.py", "--kome", adresa,
            "--naslov-datoteka", naslov_put, "--tijelo-datoteka", tijelo_put,
            "--stvarno"]


def _poziv(zahtjev, tablica, mapa):
    ljudi = zahtjev.get("primatelji")
    if not isinstance(ljudi, list) or not ljudi:
        raise Odbijeno("nijedan primatelj nije odabran")
    if len(ljudi) > NAJVISE_PRIMATELJA:
        raise Odbijeno(f"previše primatelja odjednom ({len(ljudi)})")
    for osoba in ljudi:
        if not isinstance(osoba, dict):
            raise Odbijeno("neispravan zapis primatelja")
        adresa = str(osoba.get("email", "")).strip()
        if "@" not in adresa or len(adresa.split()) != 1:
            raise Odbijeno(f"ovo ne izgleda kao adresa: {adresa!r}")
        if len(str(osoba.get("ime", ""))) > NAJDULJE_IME:
            raise Odbijeno("ime primatelja je predugačko")

    naslov_put, tijelo_put = zapisi_tekst(mapa, zahtjev)
    popis = mapa / "primatelji.json"
    popis.write_text(json.dumps(
        [{"ime": str(o.get("ime", "")).strip(), "email": str(o["email"]).strip()}
         for o in ljudi], ensure_ascii=False), encoding="utf-8")

    return ["posalji_poziv.py", "--tecaj", tablica, "--primatelji", str(popis),
            "--naslov-datoteka", naslov_put, "--tijelo-datoteka", tijelo_put,
            "--posalji"]


def _rijesi_uplatu(zahtjev, tablica, mapa):
    adresa = provjeri_adresu(zahtjev)
    ref = str(zahtjev.get("ref", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9/._-]{1,64}", ref):
        raise Odbijeno(f"neispravna oznaka uplate: {ref!r}")
    return ["bank_solo/rijesi_uplatu.py", "--ref", ref, "--email", adresa,
            "--stvarno"]


def _popis_polaznika(zahtjev, tablica, mapa):
    return ["popis_polaznika.py", "--tecaj", tablica]


def _potvrdi_greske(zahtjev, tablica, mapa):
    return ["potvrdi_greske.py"]


def _otkazi(zahtjev, tablica, mapa):
    naredba = ["otkazi_polaznika.py", "--tablica", tablica]
    if zahtjev.get("email"):
        naredba += ["--email", provjeri_adresu(zahtjev)]
    else:
        ime = str(zahtjev.get("ime", "")).strip()
        if not ime or len(ime) > NAJDULJE_IME:
            raise Odbijeno("otkazivanje treba adresu ili ime polaznika")
        naredba += ["--ime", ime]
    return naredba + ["--stvarno"]


# Jedini poslovi koji se smiju zatražiti. Sve ostalo se odbija. Vrijednost je
# funkcija koja od zahtjeva složi argumente za pokreni.sh.
POSLOVI = {
    "pregled_certifikata": _certifikati(posalji=False),
    "posalji_certifikate": _certifikati(posalji=True),
    "podsjetnik_uplata": _podsjetnik,
    "otkazi_polaznika": _otkazi,
    "rijesi_uplatu": _rijesi_uplatu,
    "posalji_poziv": _poziv,
    "popis_polaznika": _popis_polaznika,
    "potvrdi_greske": _potvrdi_greske,
}

# Poslovi koji se ne tiču nijedne tablice. Svi ostali moraju imenovati
# postojeću, jer naziv ide u naredbu.
BEZ_TABLICE = {"potvrdi_greske"}


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


def procitaj_zahtjev(put: Path) -> dict:
    """Zahtjev s provjerenim poslom i tablicom. Diže Odbijeno ako ne valja."""
    try:
        with open(put, encoding="utf-8") as f:
            zahtjev = json.load(f)
    except (ValueError, OSError) as e:
        raise Odbijeno(f"ne mogu pročitati zahtjev: {e}")
    if not isinstance(zahtjev, dict):
        raise Odbijeno("zahtjev nije u očekivanom obliku")

    if zahtjev.get("posao") not in POSLOVI:
        raise Odbijeno(f"nepoznat posao {zahtjev.get('posao')!r}")

    # Naziv tablice ide u naredbu, pa se ne uzima na vjeru nego se traži
    # među onima koje stvarno postoje.
    if zahtjev["posao"] in BEZ_TABLICE:
        zahtjev["tablica"] = ""
    elif zahtjev.get("tablica", "") not in poznate_tablice():
        raise Odbijeno(f"nema tablice {zahtjev.get('tablica')!r}")

    return zahtjev


def odradi(put: Path) -> None:
    oznaka = put.stem
    arhiva = OBRADENO / oznaka
    try:
        zahtjev = procitaj_zahtjev(put)
        posao = zahtjev["posao"]
        tablica = zahtjev["tablica"]
        argumenti = POSLOVI[posao](zahtjev, tablica, arhiva)
    except Odbijeno as e:
        print(f"[!] {put.name}: {e}")
        zabiljezi({"oznaka": oznaka, "posao": "?", "tablica": "", "osoba": "",
                   "trazio": "?", "trazeno": sada(), "gotovo": sada(),
                   "status": "odbijeno", "ispis": str(e)})
        put.unlink(missing_ok=True)
        return

    trazio = zahtjev.get("trazio", "?")
    osoba = zahtjev.get("ime") or zahtjev.get("email") or ""

    # makni zahtjev prije pokretanja: ako posao padne usred, ne pokreće se
    # ponovno sam od sebe
    arhiva.mkdir(parents=True, exist_ok=True)
    put.replace(arhiva / "zahtjev.json")

    osnova = {"oznaka": oznaka, "posao": posao, "tablica": tablica,
              "osoba": osoba, "trazio": trazio, "trazeno": sada()}
    zabiljezi(dict(osnova, status="u tijeku", ispis=""))
    print(f"=== {sada()} {posao}" + (f" / {tablica}" if tablica else "")
          + (f" / {osoba}" if osoba else "") + f" (tražio {trazio}) ===")

    naredba = [str(POKRENI), *argumenti]
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
