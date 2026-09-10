"""Slanje mail obavijesti o neuparenim bankovnim uplatama."""

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


def datumi_rijecima(dates_text: str) -> str:
    """'03.-04.10.2026.' -> '3. i 4. listopada 2026.'

    Za čitanje datuma koristi parser iz send_reminders.py (jedan izvor
    istine za sve oblike koje Emmett koristi). Ako se do njega ne može doći
    ili se datum ne može pročitati, vraća zapis kakav je u tablici."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from send_reminders import parse_course_dates
    except Exception:
        return dates_text

    prvi, zadnji = parse_course_dates(dates_text)
    if prvi is None:
        return dates_text

    if prvi == zadnji:
        return f"{prvi.day}. {MJESECI_GENITIV[prvi.month - 1]} {prvi.year}."
    if prvi.month == zadnji.month:
        return (f"{prvi.day}. i {zadnji.day}. {MJESECI_GENITIV[prvi.month - 1]} "
                f"{zadnji.year}.")
    return (f"{prvi.day}. {MJESECI_GENITIV[prvi.month - 1]} i "
            f"{zadnji.day}. {MJESECI_GENITIV[zadnji.month - 1]} {zadnji.year}.")


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

    tijelo = config.get(kljuc)
    naslov = config.get("payment_confirmation_subject")
    if not tijelo or not naslov:
        return False

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
