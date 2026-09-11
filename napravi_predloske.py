"""
Napravi Word dokumente s tekstovima poruka - jednom, na početku.

Sve poruke koje skripte šalju čitaju svoj tekst iz dokumenta uz Excel
tablice (vidi predlosci.py). Ova skripta te dokumente stvara iz tekstova
koji su dosad stajali u config.json, odnosno iz ugrađenih zadanih tekstova,
pa ih dalje uređuješ u Wordu.

    python3 napravi_predloske.py --pregled     # samo pokaži što bi napravio
    python3 napravi_predloske.py               # napravi dokumente koji fale

Postojeći dokument se NIKAD ne mijenja ni ne briše - ako ga želiš vratiti
na polazni tekst, prvo ga preimenuj ili makni.
"""

import argparse
import sys
from pathlib import Path

import predlosci
from posalji_tablicu import DEFAULT_BODY as IZVJESTAJ_BODY
from posalji_tablicu import DEFAULT_SUBJECT as IZVJESTAJ_SUBJECT
from send_reminders import ZADANI_NASLOV
from zoho_to_excel import load_config

sys.path.insert(0, str(Path(__file__).with_name("bank_solo")))


def tekstovi_potvrda():
    """Zadani tekstovi potvrda uplate - žive u bank_solo/mailer.py."""
    try:
        from bank_solo import mailer
    except ImportError:
        import mailer
    return mailer


def sastavi(naslov: str, tijelo: str) -> str:
    """Dokument počinje retkom 'Naslov: ...' pa tekstom poruke."""
    if naslov:
        return f"Naslov: {naslov}\n\n{tijelo}"
    return tijelo


def popis(config: dict) -> list:
    """[(naziv datoteke, tekst)] - sve poruke koje sustav šalje."""
    mailer = tekstovi_potvrda()
    stavke = []

    # 1. Odgovor na prijavu
    stavke.append((
        "odgovor na prijavu",
        sastavi(config.get("reply_subject",
                           "Potvrda prijave - Emmett tehnika {course_code} ({dates})"),
                config.get("reply_body", "")),
    ))
    stavke.append(("odgovor uvjeti akontacija",
                   config.get("reply_deposit_section", "")))
    stavke.append(("odgovor uvjeti puni iznos",
                   config.get("reply_no_deposit_section", "")))

    # 2. Podsjetnici
    for rule in sorted(config.get("reminders", []),
                       key=lambda r: r["days_before"], reverse=True):
        dana = rule["days_before"]
        jedinica = "dan" if dana == 1 else "dana"
        stavke.append((
            rule.get("predlozak") or f"podsjetnik {dana} {jedinica}",
            sastavi(rule.get("subject") or ZADANI_NASLOV, rule.get("body", "")),
        ))
    stavke.append(("blok uplate akontacija", config.get("reminder_deposit_block", "")))
    stavke.append(("blok uplate puni iznos", config.get("reminder_no_deposit_block", "")))

    # 3. Potvrde uplate
    naslov_potvrde = (config.get("payment_confirmation_subject")
                      or mailer.DEFAULT_SUBJECT)
    for kljuc, naziv in mailer.DOKUMENTI.items():
        stavke.append((naziv, sastavi(naslov_potvrde,
                                      config.get(kljuc) or mailer.DEFAULT_BODIES[kljuc])))

    # 4. Mail centrali nakon tečaja
    stavke.append((
        "izvjestaj centrali",
        sastavi(config.get("course_report_subject", IZVJESTAJ_SUBJECT),
                config.get("course_report_body", IZVJESTAJ_BODY)),
    ))

    return [(naziv, tekst) for naziv, tekst in stavke if tekst and tekst.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Napravi Word dokumente s tekstovima automatskih poruka.")
    parser.add_argument("--pregled", action="store_true",
                        help="Samo pokaži što bi napravio, bez pisanja")
    parser.add_argument("--mapa", help="Gdje ih napraviti (inače output_dir iz configa)")
    args = parser.parse_args()

    config = load_config()
    mapa = Path(args.mapa or config["output_dir"])
    if not mapa.exists():
        sys.exit(f"Ne postoji folder: {mapa}")

    print(f"Dokumenti s tekstovima poruka idu u: {mapa}\n")

    napravljeno = preskoceno = 0
    for naziv, tekst in popis(config):
        postoji = predlosci.nadji_dokument(mapa, naziv)
        if postoji:
            print(f"  postoji vec: {postoji.name}")
            preskoceno += 1
            continue
        put = mapa / f"{naziv}.docx"
        if args.pregled:
            print(f"  napravio bih: {put.name} ({len(tekst.splitlines())} redaka)")
        else:
            predlosci.napisi_docx(put, tekst)
            print(f"  NAPRAVLJENO:  {put.name}")
        napravljeno += 1

    print()
    if args.pregled:
        print(f"Pregled: {napravljeno} za napraviti, {preskoceno} vec postoji.")
    else:
        print(f"Gotovo: {napravljeno} novih dokumenata, {preskoceno} vec postojalo.")
        print("Uredi ih u Wordu; podaci u vitičastim zagradama se popunjavaju sami.")
    print("\nJos treba rucno: 'lokacija <grad>.docx' za svaki grad - u njemu neka "
          "prvi redak bude 'Dvorana: <naziv i adresa>', a ispod upute za dolazak.")


if __name__ == "__main__":
    main()
