"""
Slanje maila - jedno mjesto za sve skripte.

Postojalo je deset gotovo istih blokova sa `smtplib.SMTP_SSL`, svaki u svojoj
skripti. Kad se pokazalo da server ne može na port 465, trebalo ih je
promijeniti deset. Sad ih je jedan.

Vrsta šifriranja se bira po portu, jer se tako i razlikuju:

    465  izravni TLS (SMTPS) - veza je šifrirana od prve bajte
    587  STARTTLS            - veza kreće otvoreno pa se podigne u TLS
     25  STARTTLS            - isto, ali ovaj port blokira pola interneta

Oba su jednako sigurna kad se obave do kraja; razlikuju se samo u trenutku
kad šifriranje počne. Zato se port smije mijenjati u config.json bez ijedne
izmjene koda.

Na Hetznerovim serverima su 465 i 25 zatvoreni (mjera protiv neželjene
pošte), a 587 otvoren - pa ondje u config.json ide "smtp_port": 587.
"""

import smtplib
import ssl

ZADANI_PORT = 465
# Ako server ne odgovori za ovoliko, nema smisla dalje čekati - mail se
# ponavlja, a cron posao ne smije visjeti.
ISTEK = 30


def veza(config: dict):
    """Otvorena i šifrirana veza sa SMTP poslužiteljem, spremna za prijavu."""
    host = config["smtp_host"]
    port = int(config.get("smtp_port") or ZADANI_PORT)

    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=ISTEK)

    smtp = smtplib.SMTP(host, port, timeout=ISTEK)
    try:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
    except Exception:
        smtp.close()
        raise
    return smtp


def posalji(config: dict, msg) -> None:
    """Pošalji jednu poruku. Bez ponavljanja - tko ga želi, neka omota ovo
    u with_retry, kako već rade pozivatelji."""
    with veza(config) as smtp:
        smtp.login(config["zoho_email"], config["zoho_app_password"])
        smtp.send_message(msg)
