"""
Interaktivno kreira/prepravlja config.json - izbjegava ručno uređivanje
JSON-a (i tipfelere koji ga znaju pokvariti).

Pokretanje:
    python3 setup_config.py
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")

DEFAULTS = {
    "zoho_email": "nino.k@emmett-hr.com",
    "imap_host": "imap.zoho.com",
    "imap_folder": "INBOX",
    "sender_filter": "prijava@emmett-hr.com",
    "instructor_name": "Nino Kecman",
    "course_codes": [
        "Modul 1&2",
        "Modul 3",
        "Modul 4",
        "Modul 5",
        "Modul 6",
        "Ponavljanje M6 i Praktičarski dan",
    ],
    "output_dir": "/Users/ninokecman/Desktop/Prijave",
    "state_path": "processed_uids.json",
    "since_date": "2026-01-01",
    "send_replies": False,
    "smtp_host": "smtp.zoho.com",
    "smtp_port": 465,
    "reply_subject": "Potvrda prijave - {course_code}",
    "reply_body": (
        "Postovani/a {first_name},\n\n"
        "Hvala na prijavi na tecaj {course_code} u {location} ({dates}).\n\n"
        "Uskoro cete dobiti dodatne informacije.\n\n"
        "Srdacan pozdrav,\n{instructor_name}"
    ),
}


def ask(prompt: str, default: str) -> str:
    answer = input(f"{prompt} [{default}]: ").strip()
    return answer or default


def main():
    print("Postavljanje config.json - pritisni Enter da prihvatiš vrijednost u [uglatim zagradama].\n")

    config = dict(DEFAULTS)
    config["zoho_email"] = ask("Zoho email adresa", DEFAULTS["zoho_email"])
    config["imap_host"] = ask("IMAP host (imap.zoho.com ili imap.zoho.eu)", DEFAULTS["imap_host"])
    config["smtp_host"] = config["imap_host"].replace("imap.", "smtp.")
    config["output_dir"] = ask("Folder za Excel datoteke", DEFAULTS["output_dir"])
    config["since_date"] = ask("Obradi mailove od datuma (YYYY-MM-DD)", DEFAULTS["since_date"])

    app_password = ""
    while not app_password:
        app_password = input(
            "App-specific lozinka (zalijepi je ovdje - VIDJET ĆE SE na ekranu, to je ok): "
        ).strip()
        if not app_password:
            print("Prazno je, pokušaj ponovno - zalijepi lozinku pa pritisni Enter.")

    config["zoho_app_password"] = app_password

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n{CONFIG_PATH} je uspješno napravljen/ažuriran.")
    print(f"Lozinka spremljena, duljina: {len(app_password)} znakova.")


if __name__ == "__main__":
    main()
