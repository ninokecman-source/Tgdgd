"""
Interaktivno kreira config.json iz config.example.json - traži samo
tajne vrijednosti (Zoho app-lozinka, Solo API token), ostalo preuzima
iz config.example.json. Izbjegava ručno uređivanje JSON-a.

Pokretanje:
    python3 setup_config.py
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")
EXAMPLE_PATH = Path(__file__).with_name("config.example.json")


def ask_secret(label: str) -> str:
    value = ""
    while not value:
        value = input(f"{label} (zalijepi i pritisni Enter - VIDJET ĆE SE na ekranu, to je ok): ").strip()
        if not value:
            print("Prazno je, pokušaj ponovno.")
    return value


def main():
    config = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    print("Postavljanje bank_solo/config.json\n")
    config["zoho_app_password"] = ask_secret("Zoho app-specific lozinka (ista kao za glavnu Zoho skriptu)")
    config["solo_api_token"] = ask_secret("Solo API token")

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n{CONFIG_PATH} je uspješno napravljen.")
    print("Ostale vrijednosti (solo_tip_usluge, nacin_placanja, itd.) su preuzete "
          "iz config.example.json - provjeri ih ako želiš prije prvog pokretanja.")


if __name__ == "__main__":
    main()
