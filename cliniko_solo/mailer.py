"""Slanje fiskaliziranog PDF računa pacijentu mailom."""

import smtplib
import requests
from email.message import EmailMessage


def send_invoice_pdf(config, to_email, patient_name, pdf_url, broj_racuna):
    pdf_resp = requests.get(pdf_url, timeout=30)
    pdf_resp.raise_for_status()

    msg = EmailMessage()
    msg["Subject"] = f"Račun {broj_racuna}"
    msg["From"] = f"{config['smtp_from_name']} <{config['smtp_from_email']}>"
    msg["To"] = to_email
    msg.set_content(
        f"Poštovani/a {patient_name},\n\n"
        f"U prilogu se nalazi račun {broj_racuna}.\n\n"
        f"Hvala Vam!"
    )
    msg.add_attachment(
        pdf_resp.content,
        maintype="application",
        subtype="pdf",
        filename=f"{broj_racuna}.pdf",
    )

    if config["smtp_port"] == 465:
        with smtplib.SMTP_SSL(config["smtp_host"], config["smtp_port"], timeout=30) as smtp:
            smtp.login(config["smtp_username"], config["smtp_password"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=30) as smtp:
            smtp.starttls()
            smtp.login(config["smtp_username"], config["smtp_password"])
            smtp.send_message(msg)
