"""
Postavi korisničko ime i lozinku za web pregled.

Upisuje u config.json tri stvari: 'web_user', 'web_password_hash' i
'web_secret_key' (kojim Flask potpisuje kolačić prijave). Sama lozinka se
nikad ne zapisuje - samo njezin scrypt hash.

Pokretanje na serveru:

    ~/venv/bin/python ~/Tgdgd/web/postavi_lozinku.py

Prije izmjene se napravi kopija config.json.prije-izmjene, kao i kod
setup_config.py.
"""

import getpass
import json
import secrets
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lozinka

CONFIG = Path(__file__).resolve().parent.parent / "config.json"


def main():
    if not CONFIG.exists():
        sys.exit(f"Nedostaje {CONFIG}.")

    with open(CONFIG, encoding="utf-8") as f:
        config = json.load(f)

    zadani = config.get("web_user", "nino")
    korisnik = input(f"Korisničko ime [{zadani}]: ").strip() or zadani

    prva = getpass.getpass("Lozinka: ")
    if len(prva) < 10:
        sys.exit("Lozinka mora imati najmanje 10 znakova - kroz ovu stranicu "
                 "idu imena, adrese i mailovi polaznika.")
    if prva != getpass.getpass("Ponovi lozinku: "):
        sys.exit("Lozinke se ne poklapaju - ništa nije promijenjeno.")

    shutil.copy2(CONFIG, CONFIG.with_name("config.json.prije-izmjene"))

    config["web_user"] = korisnik
    config["web_password_hash"] = lozinka.napravi(prva)
    config.setdefault("web_secret_key", secrets.token_hex(32))

    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\nSpremljeno u {CONFIG}.")
    print("Pokreni web ponovno da pročita novu lozinku:")
    print("    sudo systemctl restart emmett-web")


if __name__ == "__main__":
    main()
