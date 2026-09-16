"""
Interaktivno kreira ili dopunjava config.json - traži samo tajne
vrijednosti (Zoho app-lozinka, Solo API token).

Postojeći config.json se NE briše: tvoje vrijednosti ostaju, a iz
config.example.json se dodaje samo ono čega u njemu nema (npr. nova
postavka nakon nadogradnje). Prije upisa se radi kopija
config.json.prije-izmjene.

Pokretanje:
    python3 setup_config.py
"""

import json
import shutil
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


def zadrzi_ili_pitaj(config: dict, kljuc: str, label: str) -> str:
    """Postojeća tajna se Enterom zadržava - da se pri dopuni configa ne
    mora iznova tražiti lozinka i token."""
    trenutna = config.get(kljuc, "")
    if trenutna and not str(trenutna).startswith("OVDJE"):
        odgovor = input(f"{label} (Enter = zadrži postojeću): ").strip()
        return odgovor or trenutna
    return ask_secret(label)


def main():
    # Primjer popunjava samo ono čega u postojećem configu nema.
    config = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    postojeci = {}
    if CONFIG_PATH.exists():
        try:
            postojeci = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"UPOZORENJE: {CONFIG_PATH.name} nije ispravan JSON ({e}) - "
                  f"krećem od primjera, stari ostaje u config.json.prije-izmjene.\n")
    config.update(postojeci)

    print("Postavljanje bank_solo/config.json\n")
    if postojeci:
        print("Nađen postojeći config - tvoje vrijednosti ostaju, dodajem samo "
              "ono čega nema.\n")

    config["zoho_app_password"] = zadrzi_ili_pitaj(
        config, "zoho_app_password",
        "Zoho app-specific lozinka (ista kao za glavnu Zoho skriptu)")
    config["solo_api_token"] = zadrzi_ili_pitaj(
        config, "solo_api_token", "Solo API token")

    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_name("config.json.prije-izmjene"))

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    novi = sorted(set(config) - set(postojeci)) if postojeci else []
    print(f"\n{CONFIG_PATH} je uspješno napravljen.")
    if novi:
        print(f"Dodane postavke kojih dosad nije bilo: {', '.join(novi)}")
    print("Ostale vrijednosti (solo_tip_usluge, nacin_placanja, itd.) provjeri "
          "ako želiš prije prvog pokretanja.")


if __name__ == "__main__":
    main()
