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
            f"- {tx['amount']:.2f} EUR, datum {tx['date']}, ref {tx['ref_id']}\n"
            f"  redak iz izvoda: {tx['raw_line'][:200]}"
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
