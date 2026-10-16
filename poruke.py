"""
Tekst poruka koje se šalju jednom čovjeku, na tvoju naredbu.

Razlika u odnosu na podsjetnike iz `send_reminders.py`: ondje se ista poruka
šalje svima, pa tekst ostaje predložak s oznakama tipa {first_name}. Ovdje
poruka ide jednoj osobi, pa se sve oznake odmah popune - tekst koji vidiš na
stranici je točno onaj koji će otići. Ako ga izmijeniš, šalje se tvoja
izmjena, nedirnuta.

Kao i svugdje drugdje, tekst može stajati u dokumentu uz tablice
('podsjetnik za uplatu.docx'). Ako dokumenta nema, koristi se ugrađeni.
"""


import re

import predlosci

ZADANI_NASLOV = "Podsjetnik - uplata kotizacije za {course_code}, {location}"

ZADANO_TIJELO = """Poštovani/a {first_name} {last_name},

javljamo se u vezi tečaja Emmett tehnike za ljude - {course_code}, koji se
održava {dates} u mjestu {location}.

Prema našoj evidenciji, kotizacija još nije podmirena u cijelosti:
uplaćeno je {uplaceno} EUR od ukupno {cijena} EUR, pa preostaje {manjka} EUR.

{blok_uplate}
Ako ste uplatu izvršili u međuvremenu, ovu poruku slobodno zanemarite - a
bilo bi nam od pomoći da nam to kratko javite.

Lijep pozdrav,
{instructor_name}
EMMETT Hrvatska"""


def iznos(vrijednost) -> str:
    """400.0 -> '400', 349.5 -> '349,50'. U poruci čovjeku ne stoji '400.0'."""
    try:
        broj = float(vrijednost)
    except (TypeError, ValueError):
        return str(vrijednost)
    if broj == int(broj):
        return str(int(broj))
    return f"{broj:.2f}".replace(".", ",")


def varijable(info: dict, polaznik: dict, config: dict) -> dict:
    """Sve što se smije pojaviti u tekstu poruke jednom polazniku."""
    ime = (polaznik.get("ime") or "").split()
    return {
        "first_name": ime[0] if ime else "",
        "last_name": " ".join(ime[1:]),
        "ime": polaznik.get("ime", ""),
        "email": polaznik.get("email", ""),
        "course_code": info.get("kod", ""),
        "location": info.get("mjesto", ""),
        "dates": info.get("datumi", ""),
        "instructor_name": info.get("instruktor") or config.get("instructor_name", ""),
        "uplaceno": iznos(polaznik.get("uplaceno", 0)),
        "manjka": iznos(polaznik.get("manjka", 0)),
        "cijena": iznos(info.get("cijena", "")),
        "rok_uplate": info.get("rok_uplate", ""),
        "prvi_dan": info.get("prvi_dan", ""),
    }


def podsjetnik_uplata(mapa, config: dict, info: dict, polaznik: dict):
    """(naslov, tijelo) za jednog polaznika, s već popunjenim oznakama.

    Odlomak s podacima za uplatu je isti onaj koji ide i u redovne
    podsjetnike - da se bankovni podaci upisuju na jednom mjestu."""
    from send_reminders import blok_uplate   # ovdje, da poruke.py ostane lagan

    podaci = varijable(info, polaznik, config)
    _, blok, izvor_bloka = blok_uplate(mapa, config, info.get("kod", ""))
    podaci["blok_uplate"] = (
        predlosci.popuni(blok, podaci, izvor_bloka).rstrip("\n") + "\n"
    ) if blok else ""

    naslov, tijelo, izvor = predlosci.dohvati(
        mapa, ["podsjetnik za uplatu"], config=config,
        kljuc_naslov="payment_reminder_subject",
        kljuc_tijela="payment_reminder_body",
        zadani_naslov=ZADANI_NASLOV, zadano_tijelo=ZADANO_TIJELO)

    # Ako odlomka o uplati nema, na njegovu mjestu ostane prazan redak viška.
    # Poruka ide čovjeku, pa neka izgleda kao da ju je čovjek i napisao.
    tekst = re.sub(r"\n{3,}", "\n\n", predlosci.popuni(tijelo, podaci, izvor))
    return predlosci.popuni(naslov, podaci, izvor), tekst.strip() + "\n"
