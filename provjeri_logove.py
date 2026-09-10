"""
Pregleda logove ostalih skripti i pošalje mail ako nađe problem.

Namijenjeno pokretanju iz crona (npr. svaka 3 dana). Pamti dokle je zadnji
put pročitala svaki log, pa javlja samo ono što je novo - inače bi ti svaki
put slala iste stare greške.

Javlja dvije vrste problema:

  1. GREŠKE u logu - tracebackovi, poruke koje počinju s [!] ili [GREŠKA],
     izvodi koji se ne poklapaju sa saldom, neuspjela slanja.
  2. TIŠINU - ako u nekom logu od zadnje provjere nema baš nikakvog novog
     retka, znači da se ta skripta uopće nije pokrenula (ugašen cron,
     ugašeno računalo, pobrisana skripta).

Ako nema ni jednog ni drugog, ne šalje ništa - nema smisla puniti ti
sandučić porukama "sve je u redu".

Pokretanje:
    python3 provjeri_logove.py           # tiho, javlja samo probleme
    python3 provjeri_logove.py --test    # pošalje mail bez obzira na sve
    python3 provjeri_logove.py --ispis   # ispiše nalaz umjesto slanja maila
"""

import argparse
import json
import re
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from zoho_to_excel import load_config, with_retry

STATE_PATH = Path(__file__).with_name("log_check_state.json")

# Logovi koji se prate, ako u config.json nije navedeno drugačije.
DEFAULT_LOGS = {
    "prijave i podsjetnici": str(Path(__file__).with_name("log.txt")),
    "izvodi i Solo": str(Path.home() / "Tgdgd-bank-solo" / "bank_solo" / "sync.log"),
}

# Redak se smatra problemom ako sadrži nešto od ovoga.
PROBLEM_UZORCI = [
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"\[!\]"),
    re.compile(r"\[GREŠKA\]", re.IGNORECASE),
    re.compile(r"NE VALJA"),
    re.compile(r"nije poslan", re.IGNORECASE),
    re.compile(r"ne mogu", re.IGNORECASE),
    re.compile(r"Errno"),
    re.compile(r"Error:", re.IGNORECASE),
]


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def procitaj_novo(path: Path, zadnja_pozicija: int) -> tuple:
    """Vrati (novi_tekst, nova_pozicija). Ako je log kraći nego prošli put
    (obrisan ili skraćen), čita se ispočetka."""
    velicina = path.stat().st_size
    if zadnja_pozicija > velicina:
        zadnja_pozicija = 0

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(zadnja_pozicija)
        return f.read(), velicina


def nadji_probleme(tekst: str) -> list:
    """Vrati listu problematičnih dijelova loga. Kod tracebacka se hvata
    cijeli blok, jer je zadnji redak (sama greška) ono što je zanimljivo."""
    redci = tekst.splitlines()
    problemi = []
    i = 0

    while i < len(redci):
        redak = redci[i]

        if "Traceback (most recent call last)" in redak:
            blok = [redak]
            i += 1
            # traceback traje dok su redci uvučeni; prvi neuvučeni je greška
            while i < len(redci):
                blok.append(redci[i])
                if redci[i].strip() and not redci[i].startswith(" "):
                    break
                i += 1
            problemi.append("\n".join(blok))
            i += 1
            continue

        if any(u.search(redak) for u in PROBLEM_UZORCI):
            problemi.append(redak.strip())

        i += 1

    return problemi


def broj_problema(n: int) -> str:
    """1 problem, 2-4 problema, 5+ problema - da mail ne zvuči nepismeno."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} problem"
    return f"{n} problema"


def sazmi(problemi: list, limit: int = 20) -> str:
    """Ponovljene iste greške saberi u jedan redak - log zna imati stotine
    identičnih zapisa, a njih nema smisla slati sve."""
    brojac = {}
    for p in problemi:
        brojac[p] = brojac.get(p, 0) + 1

    redci = []
    for tekst, koliko in list(brojac.items())[:limit]:
        redci.append(f"{tekst}\n   (ponovljeno {koliko}x)" if koliko > 1 else tekst)

    if len(brojac) > limit:
        redci.append(f"... i još {len(brojac) - limit} različitih problema u logu")
    return "\n\n".join(redci)


def posalji_mail(config: dict, naslov: str, tijelo: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = naslov
    msg["From"] = config["zoho_email"]
    msg["To"] = config.get("notify_email", config["zoho_email"])
    msg.set_content(tijelo)

    def _posalji():
        with smtplib.SMTP_SSL(config["smtp_host"], config.get("smtp_port", 465)) as smtp:
            smtp.login(config["zoho_email"], config["zoho_app_password"])
            smtp.send_message(msg)

    with_retry(_posalji)


def main():
    parser = argparse.ArgumentParser(description="Provjeri logove i javi greške mailom.")
    parser.add_argument("--test", action="store_true",
                        help="Pošalji mail i kad nema problema (provjera da slanje radi)")
    parser.add_argument("--ispis", action="store_true",
                        help="Ispiši nalaz u terminal umjesto slanja maila")
    args = parser.parse_args()

    config = load_config()
    state = load_state()
    logovi = config.get("watch_logs", DEFAULT_LOGS)

    prva_provjera = not state
    dijelovi = []
    ima_problema = False

    for naziv, put in logovi.items():
        path = Path(put)
        if not path.exists():
            dijelovi.append(f"### {naziv}\nLog ne postoji: {path}")
            ima_problema = True
            continue

        novi_tekst, nova_pozicija = procitaj_novo(path, state.get(str(path), 0))
        state[str(path)] = nova_pozicija

        if not novi_tekst.strip():
            if not prva_provjera:
                dijelovi.append(
                    f"### {naziv}\nNema nijednog novog retka od zadnje provjere - "
                    f"skripta se vjerojatno uopće nije pokrenula.\n({path})")
                ima_problema = True
            continue

        problemi = nadji_probleme(novi_tekst)
        if problemi:
            ima_problema = True
            dijelovi.append(f"### {naziv} - {broj_problema(len(problemi))}\n\n{sazmi(problemi)}")
        else:
            dijelovi.append(f"### {naziv}\nSve uredno "
                            f"({len(novi_tekst.splitlines())} novih redaka, bez grešaka).")

    save_state(state)

    kad = datetime.now().strftime("%d.%m.%Y. %H:%M")
    tijelo = f"Provjera logova, {kad}\n\n" + "\n\n".join(dijelovi)

    if args.ispis:
        print(tijelo)
        return

    if prva_provjera and not args.test:
        print("Prva provjera - zapamtio sam dokle su logovi pročitani, mail ne šaljem.")
        print("Za provjeru da slanje radi, pokreni s --test.")
        return

    if ima_problema:
        posalji_mail(config, f"⚠️ Emmett skripte - problem u logovima ({kad})", tijelo)
        print(f"Poslan mail o problemima na {config.get('notify_email', config['zoho_email'])}.")
    elif args.test:
        posalji_mail(config, f"✅ Emmett skripte - sve uredno ({kad})", tijelo)
        print("Poslan probni mail.")
    else:
        print("Nema problema - mail se ne šalje.")


if __name__ == "__main__":
    main()
