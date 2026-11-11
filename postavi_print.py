"""
Upiši u config.json adresu tiskare i što ide na print uz koji modul.

Dva polja:

  print_email  - kome ide narudžba
  print_items  - što sve ide uz koji modul, i u koliko primjeraka

Ključ u `print_items` mora biti kod tečaja onako kako piše u ćeliji C4 te
tablice, jer se po njemu i traži (preko kljuc_tecaja, pa kvačice i velika
slova nisu važni - slova jesu). Zato ovdje ne pišem kodove iz glave nego ih
čitam iz tablica. Ako se ključ ne poklopi, narudžba tiho ispadne nepotpuna:
pošalje se samo skripta, bez disclaimera, obrasca i potvrdnica.

Predlažu se samo moduli kojima uz skriptu ide još nešto. Za ostale nema što
upisivati - bez zapisa posalji_na_print.py ionako šalje skriptu imenovanu po
kodu tečaja, što je točno ono što treba.

Postojeći zapisi se ne diraju. Skripta usput provjeri jesu li imenovane
datoteke u mapi Print i javi koje nema.

Pokretanje (bez --stvarno samo ispiše što bi upisao):
    ~/Tgdgd/server/pokreni.sh postavi_print.py
    ~/Tgdgd/server/pokreni.sh postavi_print.py --email tiskara@primjer.com
    ~/Tgdgd/server/pokreni.sh postavi_print.py --email ... --stvarno
"""

import argparse
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

import prava
import tablice
from posalji_na_print import ZADANA_MAPA, nadji_datoteku
from predlosci import kljuc_tecaja
from send_reminders import CELL_COURSE_CODE
from zoho_to_excel import load_config, with_retry

CONFIG = Path(__file__).resolve().parent / "config.json"

# Što ide uz koji modul. Prepoznaje se po dijelu koda tečaja, malim slovima i
# bez kvačica, jer tablice ispunjava čovjek pa se zapis razlikuje.
#
#   koliko: "polaznici" (koliko ih je), "pola" (pola toliko, gore), ili broj
#   certifikati: sve gotove potvrdnice tog tečaja, svaka u jednom primjerku
# Korice tečaja: dobiva ih samo onaj tko tek ulazi u program, pa je količina
# "novi". Na Modulu 1&2 ranijih modula nema, pa su svi novi - isto pravilo
# vrijedi za cijeli niz, bez posebnog slučaja. Ponavljanje nije u nizu i
# korice ne dobiva: ti polaznici ih imaju od prije.
KORICE = [
    {"datoteka": "CourseCover", "koliko": "novi", "papir": "deblji papir",
     # "papir" se ne ponavlja u napomeni - polje iznad već kaže koji je.
     "napomena": "jednostrano na jedan list, u koloru"},
    {"datoteka": "CourseCover- spine", "koliko": "novi",
     "papir": "deblji papir", "napomena": "u koloru"},
]

# Napomene koje su u configu ostale od ranije, a više ne odgovaraju uputi.
# Samo one se smiju prepisati - tako ispravak stigne do zapisa koji već
# postoji, a da se ne pregazi ništa što si sam podesio.
ZASTARJELE_NAPOMENE = {"na dvije stranice",
                       "na jedan papir, jednostrano, u koloru"}

PRAVILA = [
    ("modul 1&2", [
        {"datoteka": "Disclaimer"},
        {"datoteka": "Zdravstveni obrazac", "koliko": "pola"},
    ]),
    ("ponavljanje", [
        {"datoteka": "Praktičarski ispit"},
        {"certifikati": True, "papir": "tvrđi papir"},
    ]),
]


def kodovi_iz_tablica(output_dir: Path) -> list:
    kodovi = []
    for put in tablice.nadji(output_dir, javi=lambda poruka: print(f"  {poruka}")):
        wb = with_retry(lambda: load_workbook(put), retry_on=(PermissionError, OSError))
        if "podaci" not in wb.sheetnames:
            continue
        kod = " ".join(str(wb["podaci"][CELL_COURSE_CODE].value or "").split())
        if kod and kod not in kodovi:
            kodovi.append(kod)
    return kodovi


def uredan_naziv(put: Path) -> str:
    """Naziv datoteke bez nastavka i bez viška razmaka.

    Neke datoteke u mapi imaju razmak na kraju naziva ('Modul1&2-2020 .pdf').
    Usporedba to podnosi, jer kljuc_tecaja sabija razmake, ali u config ne
    treba ulaziti - ondje bi izgledao kao greška."""
    return " ".join(put.stem.split())


def kljuc_datoteke(naziv: str) -> str:
    """Naziv sveden na slova i cifre: 'Modul1&2-2020' i 'Modul 1&2' postaju
    'modul122020' i 'modul12'. Razmaci, crtice i & otpadaju, jer se u nazivu
    datoteke pišu drukčije nego u ćeliji C4."""
    return "".join(z for z in kljuc_tecaja(naziv) if z.isalnum())


def nadji_skriptu(mapa: Path, kod: str):
    """Datoteka skripte za taj modul, ili None.

    Skripte se u mapi ne zovu točno kao kod tečaja ('Modul1&2-2020' za
    'Modul 1&2'), pa točno poklapanje ne prolazi. Traži se datoteka čiji
    naziv POČINJE kodom, i to samo ako je takva jedna jedina - inače se ne
    pogađa. Točno poklapanje, ako postoji, ima prednost."""
    if not mapa.is_dir():
        return None
    datoteke = [p for p in sorted(mapa.iterdir())
                if p.is_file() and not p.name.startswith("~$")]
    trazeni = kljuc_datoteke(kod)
    for p in datoteke:
        if kljuc_datoteke(p.stem) == trazeni:
            return p
    # Prefiks vrijedi samo kad je ostatak cifra - skripte se razlikuju
    # godinom ('Modul1&2-2020'). Da se gledala bilo kakva dopuna, 'CourseCover'
    # bi se uhvatio za 'CourseCover- spine' kad prvog nema.
    pocinju = [p for p in datoteke
               if kljuc_datoteke(p.stem).startswith(trazeni)
               and kljuc_datoteke(p.stem)[len(trazeni):].isdigit()]
    return pocinju[0] if len(pocinju) == 1 else None


def oznaka_stavke(zapis) -> str:
    """Po čemu se dvije stavke smatraju istom."""
    if not isinstance(zapis, dict):
        return str(zapis)
    if zapis.get("certifikati"):
        return "certifikati"
    return kljuc_tecaja(zapis.get("datoteka") or "")


def popravi_nazive(stavke, mapa_print: Path, predlozene: list) -> tuple:
    """(dopunjene stavke, [poruke o promjenama]) za zapis koji već postoji.

    Dvije stvari, obje uske:

    - naziv datoteke koje u mapi nema popravi se, ali samo kad se jedna
      jedina očito odnosi na nju
    - stavka koju pravilo traži a u zapisu je nema se dopiše na kraj

    Količine, papir i redoslijed postojećih stavki ostaju kakvi jesu. Zapis
    upisan prije nego su korice uopće postojale inače ih nikad ne bi dobio -
    'već upisan, ne diram' bi ga zauvijek ostavio nepotpunim."""
    if not isinstance(stavke, list):
        return stavke, []
    nove, promjene = [], []
    for zapis in stavke:
        if not isinstance(zapis, dict):
            nove.append(zapis)
            continue
        zapis = dict(zapis)
        naziv = zapis.get("datoteka")
        if naziv and nadji_datoteku(mapa_print, naziv) is None:
            put = nadji_skriptu(mapa_print, naziv)
            if put is not None and uredan_naziv(put) != naziv:
                promjene.append(f"{naziv!r} -> {uredan_naziv(put)!r}")
                zapis["datoteka"] = uredan_naziv(put)
        nove.append(zapis)

    # Ispravak upute za stavku koja je upisana po starom pravilu.
    po_pravilu = {oznaka_stavke(z): z for z in predlozene}
    for zapis in nove:
        pravilo = po_pravilu.get(oznaka_stavke(zapis))
        if not isinstance(zapis, dict) or pravilo is None:
            continue
        # Prazno polje se smije popuniti - prazno znači da ništa nije
        # birano. Ispisana napomena se mijenja samo ako je jedna od onih
        # koje je skripta sama upisala po starom pravilu.
        stara = (zapis.get("napomena") or "").strip()
        if pravilo.get("napomena") and (not stara or stara in ZASTARJELE_NAPOMENE):
            zapis["napomena"] = pravilo["napomena"]
            promjene.append(f"{zapis.get('datoteka', '?')}: uputa "
                            + (f"{stara!r} -> " if stara else "")
                            + repr(pravilo["napomena"]))
        if pravilo.get("papir") and not zapis.get("papir"):
            zapis["papir"] = pravilo["papir"]
            promjene.append(f"{zapis.get('datoteka', '?')}: papir "
                            f"{pravilo['papir']!r}")

    ima = {oznaka_stavke(z) for z in nove}
    for zapis in predlozene:
        if oznaka_stavke(zapis) in ima:
            continue
        nove.append(dict(zapis))
        ima.add(oznaka_stavke(zapis))
        opis = ("sve potvrdnice tog tečaja" if zapis.get("certifikati")
                else zapis.get("datoteka"))
        promjene.append(f"dopisano: {opis}")
    return nove, promjene


def stavke_za_kod(kod: str, mapa_print: Path, config: dict) -> list:
    """Što ide na print za taj kod tečaja, s pravim nazivima datoteka.

    U config se upisuje naziv datoteke kakav u mapi stvarno jest, a ne kod
    tečaja - inače posalji_na_print.py tu datoteku ne nađe, jer uspoređuje
    točno. Skripta se dodaje samo ako postoji: ponavljanje M6 je nema, a i
    ne treba mu - njemu idu praktičarski ispit i potvrdnice."""
    import pozivi

    stavke = []
    skripta = nadji_skriptu(mapa_print, kod)
    if skripta is not None:
        stavke.append({"datoteka": uredan_naziv(skripta)})

    kljuc = kljuc_tecaja(kod)
    if kljuc in pozivi.redoslijed(config):
        for zapis in KORICE:
            zapis = dict(zapis)
            put = nadji_skriptu(mapa_print, zapis["datoteka"])
            if put is not None:
                zapis["datoteka"] = uredan_naziv(put)
            stavke.append(zapis)

    for dio, dodatne in PRAVILA:
        if kljuc_tecaja(dio) in kljuc:
            for zapis in dodatne:
                zapis = dict(zapis)
                naziv = zapis.get("datoteka")
                if naziv:
                    # i ovdje pravi naziv, da se 'PRAKTIČARSKI ISPIT' upiše
                    # kako piše, a ne kako sam ga ja nazvao
                    put = nadji_datoteku(mapa_print, naziv)
                    zapis["datoteka"] = uredan_naziv(put) if put else naziv
                stavke.append(zapis)
            break
    return stavke


def main():
    parser = argparse.ArgumentParser(
        description="Upiši adresu tiskare i popis za print u config.json.")
    parser.add_argument("--email", help="Adresa tiskare (print_email)")
    parser.add_argument("--stvarno", action="store_true",
                        help="Stvarno upiši; bez ovoga je samo pregled")
    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    # Kodovi iz tablica, pa oni iz course_codes kojih ondje još nema.
    # Modul koji još nije imao prijava nema tablicu, ali mu skripta za print
    # već stoji u mapi - bolje ga podesiti sad nego da narudžba padne na dan
    # kad tečaj krene.
    print("Kodovi tečajeva")
    iz_tablica = kodovi_iz_tablica(output_dir)
    kodovi = list(iz_tablica)
    vec = {kljuc_tecaja(k) for k in kodovi}
    for kod in config.get("course_codes") or []:
        kod = " ".join(str(kod).split())
        if kod and kljuc_tecaja(kod) not in vec:
            kodovi.append(kod)
            vec.add(kljuc_tecaja(kod))
    for kod in kodovi:
        print(f"  {kod}" + ("" if kod in iz_tablica else "   (još nema tablicu)"))
    if not kodovi:
        sys.exit("\nNi tablice ni 'course_codes' nemaju nijedan kod tečaja - "
                 "ne znam što bih upisao, pa ne diram config.")

    # --- adresa ---------------------------------------------------------
    stara_adresa = (config.get("print_email") or "").strip()
    nova_adresa = (args.email or "").strip()
    print("\nAdresa tiskare (print_email)")
    if nova_adresa and "@" not in nova_adresa:
        sys.exit(f"  {nova_adresa!r} ne izgleda kao adresa.")
    if nova_adresa and nova_adresa != stara_adresa:
        print(f"  {stara_adresa or '(nije upisana)'} -> {nova_adresa}")
    elif stara_adresa:
        print(f"  ostaje {stara_adresa}")
    else:
        print("  nije upisana - dodaj --email, inače slanje u tiskaru neće "
              "raditi")

    # --- stavke ---------------------------------------------------------
    postojece = dict(config.get("print_items") or {})
    imaju = {kljuc_tecaja(k) for k in postojece}
    novi, popravci = {}, {}
    print("\nŠto ide na print (print_items)")
    mapa_print = output_dir / config.get("print_folder", ZADANA_MAPA)
    for kod in kodovi:
        stavke = stavke_za_kod(kod, mapa_print, config)
        if not stavke and kljuc_tecaja(kod) not in imaju:
            print(f"  {kod}: nema se što upisati")
            continue
        if kljuc_tecaja(kod) in imaju:
            # Zapis postoji, ali može pokazivati na datoteku koje nema - tako
            # je ostalo kad se u config upisao kod tečaja umjesto naziva
            # datoteke. Sadržaj se ne mijenja, samo se naziv popravi na onaj
            # koji u mapi stvarno stoji, i to samo ako je nedvojben.
            stari = next(v for k, v in postojece.items()
                         if kljuc_tecaja(k) == kljuc_tecaja(kod))
            popravljen, promjene = popravi_nazive(stari, mapa_print, stavke)
            if promjene:
                popravci[kod] = popravljen
                print(f"  {kod}: upisan, ali nije kako treba")
                for poruka in promjene:
                    print(f"    {poruka}")
            else:
                print(f"  {kod}: već upisan, ne diram")
            continue
        novi[kod] = stavke
        print(f"  {kod}:")
        for s in stavke:
            if s.get("certifikati"):
                print(f"    - sve potvrdnice tog tečaja, {s['papir']}")
            else:
                koliko = {"pola": "pola broja polaznika",
                          "novi": "koliko ih je prvi put u programu",
                          None: "koliko i polaznika"}.get(s.get("koliko"),
                                                          s.get("koliko"))
                dodatno = [s[k] for k in ("papir", "napomena") if s.get(k)]
                print(f"    - {s['datoteka']}: {koliko}"
                      + ("".join(f", {x}" for x in dodatno)))

    # --- jesu li datoteke u mapi Print ----------------------------------
    print(f"\nDatoteke u mapi {mapa_print.name}")
    trazene = []
    pregledati = list(novi.values()) + list(popravci.values()) + [
        v for k, v in postojece.items()
        if kljuc_tecaja(k) not in {kljuc_tecaja(x) for x in popravci}]
    for stavke in pregledati:
        for s in stavke if isinstance(stavke, list) else []:
            naziv = s.get("datoteka")
            if naziv and naziv not in trazene:
                trazene.append(naziv)
    fali = []
    for naziv in trazene:
        put = nadji_datoteku(mapa_print, naziv) if mapa_print.is_dir() else None
        print(f"  {'ima' if put else 'NEMA'}  {naziv}"
              + (f"  ({put.name})" if put else ""))
        if not put:
            fali.append(naziv)
    if fali:
        print(f"\n  Stavi ih u {mapa_print} - nastavak nije važan (.pdf, .docx),")
        print("  naziv jest. Bez njih slanje u tiskaru odbija poslati "
              "nepotpunu narudžbu.")

    # --- upis -----------------------------------------------------------
    mijenjam = (bool(novi) or bool(popravci)
                or (nova_adresa and nova_adresa != stara_adresa))
    if not mijenjam:
        print("\nNema se što upisati.")
        return
    if not args.stvarno:
        print("\nPregled - ništa nije upisano. Za upis dodaj --stvarno")
        return

    with open(CONFIG, encoding="utf-8") as f:
        na_disku = json.load(f)
    if nova_adresa:
        na_disku["print_email"] = nova_adresa
    if novi or popravci:
        spojeno = dict(postojece)
        for kod, stavke in popravci.items():
            kljuc = kljuc_tecaja(kod)
            for k in list(spojeno):
                if kljuc_tecaja(k) == kljuc:
                    spojeno[k] = stavke
        na_disku["print_items"] = {**spojeno, **novi}

    kopija = CONFIG.with_name(CONFIG.name + ".prije-printa")
    prava.kopiraj(CONFIG, kopija)
    privremeno = CONFIG.with_name(CONFIG.name + ".tmp")
    with open(privremeno, "w", encoding="utf-8") as f:
        json.dump(na_disku, f, ensure_ascii=False, indent=2)
        f.write("\n")
    privremeno.replace(CONFIG)
    prava.zakljucaj(CONFIG)
    print(f"\nUpisano u {CONFIG.name} (kopija: {kopija.name}).")
    print("Provjeri narudžbu, bez slanja:")
    print('    ~/Tgdgd/server/pokreni.sh posalji_na_print.py --tecaj "Modul 1&2 Split.xlsx"')


if __name__ == "__main__":
    main()
