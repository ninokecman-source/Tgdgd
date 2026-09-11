"""Mail obavijesti iz bankovnog dijela: potvrda uplate polazniku i
obavijest tebi o uplati koja se nije dala upariti.

Tekst potvrda stoji u dokumentima uz Excel tablice ('potvrda uplate
akontacija.docx', '... doplata', '... modul', '... program') - isti princip
kao podsjetnici, vidi predlosci.py u glavnom folderu."""

import smtplib
from email.message import EmailMessage


def send_unmatched_notification(config, unmatched):
    """unmatched: lista dictova {amount, date, ref_id, raw_line}."""
    if not unmatched:
        return

    lines = []
    for tx in unmatched:
        lines.append(
            f"- {tx['amount']:.2f} EUR, datum {tx['date']}\n"
            f"  uplatitelj: {tx.get('name') or '(nepoznat)'}\n"
            f"  opis:       {tx.get('description') or '(nema)'}\n"
            f"  IBAN:       {tx.get('iban') or '(nepoznat)'}\n"
            f"  ref:        {tx['ref_id']}"
        )

    body = (
        f"Sljedeće bankovne uplate nisu automatski uparene s poznatim polaznikom "
        f"i treba ih ručno provjeriti:\n\n" + "\n\n".join(lines) +
        "\n\nOtvori Excel tablice i/ili Zoho prijave da vidiš je li osoba stvarno "
        "prijavljena, ili ručno izradi Solo ponudu."
    )

    msg = EmailMessage()
    msg["Subject"] = f"⚠️ {len(unmatched)} neuparena/e bankovna/e uplata/e - treba ručna provjera"
    msg["From"] = config["zoho_email"]
    msg["To"] = config.get("notify_email", config["zoho_email"])
    msg.set_content(body)

    if config.get("smtp_port", 465) == 465:
        with smtplib.SMTP_SSL(config["smtp_host"], config["smtp_port"], timeout=30) as smtp:
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)


# --- Potvrda uplate polazniku ------------------------------------------------

MJESECI_GENITIV = [
    "siječnja", "veljače", "ožujka", "travnja", "svibnja", "lipnja",
    "srpnja", "kolovoza", "rujna", "listopada", "studenoga", "prosinca",
]


def _iz_glavnog_foldera(naziv):
    """Uvezi modul iz glavnog foldera projekta (predlosci, send_reminders) -
    bank_solo je podmapa, pa put treba dodati ručno. Vrati None ako ne ide."""
    try:
        import importlib
        import sys
        from pathlib import Path as _Path
        koren = str(_Path(__file__).resolve().parent.parent)
        if koren not in sys.path:
            sys.path.insert(0, koren)
        return importlib.import_module(naziv)
    except Exception:
        return None


def datumi_rijecima(dates_text: str) -> str:
    """'03.-04.10.2026.' -> '3. i 4. listopada 2026.'

    Za čitanje datuma koristi parser iz send_reminders.py (jedan izvor
    istine za sve oblike koje Emmett koristi). Ako se do njega ne može doći
    ili se datum ne može pročitati, vraća zapis kakav je u tablici."""
    modul = _iz_glavnog_foldera("send_reminders")
    if modul is None:
        return dates_text

    prvi, zadnji = modul.parse_course_dates(dates_text)
    if prvi is None:
        return dates_text

    if prvi == zadnji:
        return f"{prvi.day}. {MJESECI_GENITIV[prvi.month - 1]} {prvi.year}."
    if prvi.month == zadnji.month:
        return (f"{prvi.day}. i {zadnji.day}. {MJESECI_GENITIV[prvi.month - 1]} "
                f"{zadnji.year}.")
    return (f"{prvi.day}. {MJESECI_GENITIV[prvi.month - 1]} i "
            f"{zadnji.day}. {MJESECI_GENITIV[zadnji.month - 1]} {zadnji.year}.")


# Zadani tekstovi potvrde. Koriste se kad ih config.json ne navodi - tako
# potvrde rade odmah, a tko želi drukčiji tekst, upiše svoj ključ u config
# i on ima prednost.
DEFAULT_SUBJECT = 'Potvrda uplate - Emmett tehnika {course_code}, {location}'

DEFAULT_PARTIAL = 'Poštovani/a {first_name} {last_name},\n\nhvala vam na uplati za tečaj Emmett tehnike za ljude - {course_code}, koji će se održati {datumi_rijecima} u mjestu {location}.\n\nOvim putem potvrđujemo da smo zaprimili vašu uplatu u iznosu od {iznos} EUR.\n\nTime je vaše mjesto na tečaju rezervirano. Za podmirenje kotizacije u cijelosti preostaje još {preostalo} EUR, koje je potrebno uplatiti najkasnije tjedan dana prije početka tečaja.\n\nSve ostale informacije vezane uz lokaciju, raspored i potrebnu opremu dobit ćete pravovremeno prije početka tečaja.\n\nAko imate bilo kakvih pitanja ili vam je potrebna dodatna informacija, slobodno nam se javite.\n\nVidimo se uskoro!\n\nLijep pozdrav,\n{instructor_name}\nEMMETT Hrvatska'

DEFAULT_FULL = 'Poštovani/a {first_name} {last_name},\n\nhvala vam na doplati kotizacije za tečaj Emmett tehnike za ljude - {course_code}, koji će se održati {datumi_rijecima} u mjestu {location}.\n\nOvim putem potvrđujemo da smo zaprimili vašu uplatu u iznosu od {iznos} EUR, čime je kotizacija u cijelosti podmirena (ukupno {ukupno_uplaceno} EUR).\n\nVaša prijava za tečaj je time potvrđena i veselimo se vašem dolasku.\n\nSve ostale informacije vezane uz lokaciju, raspored i potrebnu opremu dobit ćete pravovremeno prije početka tečaja.\n\nAko imate bilo kakvih pitanja ili vam je potrebna dodatna informacija, slobodno nam se javite.\n\nVidimo se uskoro!\n\nLijep pozdrav,\n{instructor_name}\nEMMETT Hrvatska'

DEFAULT_MODULE = 'Poštovani/a {first_name} {last_name},\n\nhvala vam na uplati kotizacije za tečaj Emmett tehnike za ljude - {course_code}, koji će se održati {datumi_rijecima} u mjestu {location}.\n\nOvim putem potvrđujemo da smo zaprimili vašu uplatu u iznosu od {iznos} EUR, čime je kotizacija za tečaj u cijelosti podmirena.\n\nVaša prijava za tečaj je time potvrđena i veselimo se vašem dolasku.\n\nSve ostale informacije vezane uz lokaciju, raspored i potrebnu opremu dobit ćete pravovremeno prije početka tečaja.\n\nAko imate bilo kakvih pitanja ili vam je potrebna dodatna informacija, slobodno nam se javite.\n\nVidimo se uskoro!\n\nLijep pozdrav,\n{instructor_name}\nEMMETT Hrvatska'

DEFAULT_COURSE = 'Poštovani/a {first_name} {last_name},\n\nhvala vam na uplati kotizacije za cijeli program Emmett tehnike za ljude.\n\nOvim putem potvrđujemo da smo zaprimili vašu uplatu u iznosu od {iznos} EUR, čime je kotizacija za sve module u cijelosti podmirena.\n\nPrvi tečaj na koji ste prijavljeni, {course_code}, održat će se {datumi_rijecima} u mjestu {location}. Za svaki sljedeći modul javit ćemo vam se s detaljima pravovremeno, pa ne morate ništa dodatno uplaćivati.\n\nVaša prijava je time potvrđena i veselimo se vašem dolasku.\n\nSve ostale informacije vezane uz lokaciju, raspored i potrebnu opremu dobit ćete pravovremeno prije početka tečaja.\n\nAko imate bilo kakvih pitanja ili vam je potrebna dodatna informacija, slobodno nam se javite.\n\nVidimo se uskoro!\n\nLijep pozdrav,\n{instructor_name}\nEMMETT Hrvatska'

DEFAULT_BODIES = {
    "payment_confirmation_body_partial": DEFAULT_PARTIAL,
    "payment_confirmation_body_full": DEFAULT_FULL,
    "payment_confirmation_body_module": DEFAULT_MODULE,
    "payment_confirmation_body_course": DEFAULT_COURSE,
}

# Svaka potvrda ima svoj dokument uz Excel tablice - isto kao podsjetnici.
# Uredi ga u Wordu i sljedeća potvrda ide s novim tekstom.
DOKUMENTI = {
    "payment_confirmation_body_partial": "potvrda uplate akontacija",
    "payment_confirmation_body_full": "potvrda uplate doplata",
    "payment_confirmation_body_module": "potvrda uplate modul",
    "payment_confirmation_body_course": "potvrda uplate program",
}


def send_payment_confirmation(config, registrant, iznos, ukupno_uplaceno):
    """Javi polazniku da je uplata zaprimljena. Tekst se razlikuje ovisno o
    tome je li kotizacija time podmirena u cijelosti ili još nešto preostaje
    - tako jedna te ista poruka pokriva akontaciju, doplatu i punu uplatu."""
    to_email = (registrant.get("email") or "").strip()
    if not to_email:
        return False

    cijena = config.get("price_total")
    cijena_tecaja = config.get("course_total_price")
    preostalo = max(0, cijena - ukupno_uplaceno) if cijena is not None else 0

    # Koji tekst ide - po tome što je ta uplata pokrila:
    #   cijeli program (2400)  -> uplaćeni su svi moduli odjednom
    #   cijeli modul (400)     -> jedna uplata pokrila cijelu kotizaciju
    #   doplata                -> ranija akontacija + ova uplata zatvaraju iznos
    #   djelomično             -> nešto još preostaje
    if cijena_tecaja is not None and abs(iznos - cijena_tecaja) < 0.01:
        kljuc = "payment_confirmation_body_course"
    elif cijena is not None and abs(iznos - cijena) < 0.01:
        kljuc = "payment_confirmation_body_module"
    elif cijena is None or preostalo <= 0.01:
        kljuc = "payment_confirmation_body_full"
    else:
        kljuc = "payment_confirmation_body_partial"

    varijable = {
        "first_name": registrant.get("first_name", ""),
        "last_name": registrant.get("last_name", ""),
        "course_code": registrant.get("course_code", ""),
        "location": registrant.get("location", ""),
        "dates": registrant.get("dates", ""),
        "datumi_rijecima": datumi_rijecima(registrant.get("dates", "")),
        "iznos": f"{iznos:g}",
        "ukupno_uplaceno": f"{ukupno_uplaceno:g}",
        "preostalo": f"{preostalo:g}",
        "cijena": f"{cijena:g}" if cijena is not None else "",
        "cijena_tecaja": f"{cijena_tecaja:g}" if cijena_tecaja is not None else "",
        "instructor_name": config.get("instructor_name", ""),
    }

    # Tekst: dokument uz tablice -> config.json -> ugrađeni tekst.
    predlosci = _iz_glavnog_foldera("predlosci")
    if predlosci is not None:
        from pathlib import Path
        naslov, tijelo, izvor = predlosci.dohvati(
            Path(config["excel_dir"]), DOKUMENTI[kljuc], config=config,
            kljuc_naslov="payment_confirmation_subject", kljuc_tijela=kljuc,
            zadani_naslov=DEFAULT_SUBJECT, zadano_tijelo=DEFAULT_BODIES[kljuc])
        print(f"  (tekst potvrde: {izvor})")
    else:
        tijelo = config.get(kljuc) or DEFAULT_BODIES[kljuc]
        naslov = config.get("payment_confirmation_subject") or DEFAULT_SUBJECT

    msg = EmailMessage()
    msg["Subject"] = naslov.format(**varijable)
    msg["From"] = config["zoho_email"]
    msg["To"] = to_email
    msg.set_content(tijelo.format(**varijable))

    if config.get("smtp_port", 465) == 465:
        with smtplib.SMTP_SSL(config["smtp_host"], config["smtp_port"], timeout=30) as smtp:
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)
    return True
