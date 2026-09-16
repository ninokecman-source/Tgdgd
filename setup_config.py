"""
Interaktivno kreira ili dopunjava config.json - izbjegava ručno uređivanje
JSON-a (i tipfelere koji ga znaju pokvariti).

Postojeći config.json se NE briše: mijenjaju se samo vrijednosti koje sam
upišeš, a sve ostalo (tekstovi poruka, podsjetnici, adrese centrale,
uključeni prekidači) ostaje kako jest. Prije upisa se radi kopija
config.json.prije-izmjene.

Pokretanje:
    python3 setup_config.py
"""

import json
import shutil
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")

DEFAULTS = {
    "zoho_email": "nino.k@emmett-hr.com",
    "imap_host": "imap.zoho.com",
    "folder_roots": ["Split", "Zagreb"],
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


def ucitaj_postojeci() -> dict:
    """Postojeći config je polazište - inače bi se izgubilo sve što u
    DEFAULTS ne postoji (tekstovi poruka, podsjetnici, prekidači)."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"UPOZORENJE: {CONFIG_PATH.name} nije ispravan JSON ({e}).")
        print("Krećem od praznog - stari ostaje u config.json.prije-izmjene.\n")
        return {}


def main():
    print("Postavljanje config.json - pritisni Enter da prihvatiš vrijednost u [uglatim zagradama].\n")

    postojeci = ucitaj_postojeci()
    if postojeci:
        print(f"Nađen postojeći {CONFIG_PATH.name} - mijenjam samo ono što upišeš, "
              f"ostalo ostaje netaknuto.\n")

    # Postojeće vrijednosti su polazište; DEFAULTS popunjava samo ono čega nema.
    config = dict(DEFAULTS)
    config.update(postojeci)

    def trenutno(kljuc):
        return str(config.get(kljuc, DEFAULTS.get(kljuc, "")))

    config["zoho_email"] = ask("Zoho email adresa", trenutno("zoho_email"))
    config["imap_host"] = ask("IMAP host (imap.zoho.com ili imap.zoho.eu)", trenutno("imap_host"))
    config["smtp_host"] = config["imap_host"].replace("imap.", "smtp.")
    config["output_dir"] = ask("Folder za Excel datoteke", trenutno("output_dir"))
    config["since_date"] = ask("Obradi mailove od datuma (YYYY-MM-DD)", trenutno("since_date"))

    stara_lozinka = config.get("zoho_app_password", "")
    if stara_lozinka:
        print("\nApp-lozinka je već spremljena. Enter je zadržava, ili upiši novu.")
        app_password = input("Nova app-specific lozinka (Enter = zadrži staru): ").strip()
        app_password = app_password or stara_lozinka
    else:
        app_password = ""
        while not app_password:
            app_password = input(
                "App-specific lozinka (zalijepi je ovdje - VIDJET ĆE SE na ekranu, to je ok): "
            ).strip()
            if not app_password:
                print("Prazno je, pokušaj ponovno - zalijepi lozinku pa pritisni Enter.")

    config["zoho_app_password"] = app_password

    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_name("config.json.prije-izmjene"))

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    zadrzano = sorted(set(postojeci) - set(DEFAULTS))
    print(f"\n{CONFIG_PATH} je uspješno napravljen/ažuriran.")
    print(f"Lozinka spremljena, duljina: {len(app_password)} znakova.")
    if zadrzano:
        print(f"Zadržano netaknuto: {', '.join(zadrzano)}")


if __name__ == "__main__":
    main()
