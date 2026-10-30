"""
Zapamti dokle su logovi pročitani, da brojač grešaka na stranici krene
ispočetka.

Greške koje web pregled broji nisu nigdje zapisane - svaki put se iznova
pročitaju iz logova. Zato se "reset" ne može napraviti brisanjem: logovi
moraju ostati čitavi. Umjesto toga se za svaki log zapamti njegova trenutna
veličina, a web/skupi.py onda broji samo ono što se u njemu pojavi poslije
te točke.

Ako log u međuvremenu postane manji - netko ga je skratio ili se zarotirao -
zapamćena točka se za taj log zanemaruje i opet se gleda sve.

Pokreće ga tipka "Kreni ispočetka" na stranici Stanje, preko
server/izvrsi.py. Ručno:

    ~/Tgdgd/server/pokreni.sh potvrdi_greske.py
"""

import json
from datetime import datetime
from pathlib import Path

from provjeri_logove import DEFAULT_LOGS
from zoho_to_excel import load_config

STANJE = Path(__file__).with_name("greske_potvrdene.json")


def main():
    config = load_config()
    logovi = {}
    for naziv, put_tekst in config.get("watch_logs", DEFAULT_LOGS).items():
        put = Path(put_tekst).expanduser()
        if not put.exists():
            continue
        logovi[naziv] = {"put": str(put), "velicina": put.stat().st_size}

    stanje = {"kada": datetime.now().isoformat(timespec="seconds"),
              "logovi": logovi}
    with open(STANJE, "w", encoding="utf-8") as f:
        json.dump(stanje, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"Brojač grešaka kreće ispočetka od {stanje['kada']}.")
    for naziv, podaci in sorted(logovi.items()):
        print(f"  {naziv}: sve do {podaci['velicina']} B smatra se viđenim")
    if not logovi:
        print("  Nijedan praćeni log ne postoji - nema se što zapamtiti.")


if __name__ == "__main__":
    main()
