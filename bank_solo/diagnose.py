"""
Dijagnostika za bank_solo.

Bez argumenata: zašto pretraga ne pronalazi mailove s bankovnim izvodima
u 'Izvodi' folderu.

    python3 diagnose.py

S --izvod: dohvati zadnje izvode i pokaži svaku transakciju - uplate,
isplate, ime uplatitelja i opis plaćanja - te poklapa li se promet sa
saldom izvoda. Ako negdje piše "NE VALJA", taj izvod se ne obrađuje i
treba pogledati zašto.

    python3 diagnose.py --izvod

Ispis namjerno NE prikazuje cijeli redak izvoda (sadrži IBAN i ime
uplatitelja). Ako ga stvarno trebaš vidjeti, dodaj --puni-redak.
"""

import argparse
import email
import imaplib
import json
import sys
from email import policy
from pathlib import Path

from statement_parser import parse_statement

CONFIG_PATH = Path(__file__).with_name("config.json")


def maskiraj(line: str) -> str:
    """Zamijeni svaku znamenku s 9 i svako slovo s A, ostalo ostavi. Tako
    se vidi raspored polja u retku izvoda (gdje su iznosi, datumi, oznake)
    bez ijednog stvarnog podatka - ni IBAN-a ni imena."""
    return "".join("9" if ch.isdigit() else ("A" if ch.isalpha() else ch) for ch in line)


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Nema {CONFIG_PATH}.\n"
            "bank_solo ima svoj config, odvojen od glavnog. Napravi ga s:\n"
            "    python3 setup_config.py\n"
            "(traži samo Zoho app-lozinku i Solo API token, ostalo je već upisano)."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def connect(config):
    imap = imaplib.IMAP4_SSL(config["imap_host"])
    imap.login(config["zoho_email"], config["zoho_app_password"])
    return imap


def diagnose_folder(config, imap):
    folder = config.get("imap_folder", "INBOX")
    status, data = imap.select(f'"{folder}"')
    print(f"SELECT {folder!r} -> status={status}, broj poruka={data}")

    print(f"\n=== SVI mailovi u {folder!r} (bez FROM filtera) ===")
    status, data = imap.uid("search", None, "ALL")
    all_uids = data[0].split() if data and data[0] else []
    print(f"Ukupno: {len(all_uids)}")

    for uid in all_uids[-10:]:
        status, msg_data = imap.uid("fetch", uid, "(RFC822.HEADER)")
        if status != "OK" or not msg_data or msg_data[0] is None:
            continue
        msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
        print(f"  UID {uid.decode()}: From={msg['From']!r}  Date={msg['Date']!r}  "
              f"Subject={msg['Subject']!r}")

    print(f"\n=== Pretraga FROM \"{config['bank_sender']}\" ===")
    status, data = imap.uid("search", None, f'(FROM "{config["bank_sender"]}")')
    matched_uids = data[0].split() if data and data[0] else []
    print(f"Pronađeno: {len(matched_uids)} -> {matched_uids}")


def diagnose_statements(config, imap, koliko: int, puni_redak: bool, maska: bool):
    folder = config.get("imap_folder", "INBOX")
    imap.select(f'"{folder}"')
    status, data = imap.uid("search", None, f'(FROM "{config["bank_sender"]}")')
    uids = data[0].split() if data and data[0] else []
    if not uids:
        print(f"Nema nijednog maila od {config['bank_sender']!r} u folderu {folder!r}.")
        return

    print("Smjer se čita iz koda tipa transakcije i provjerava protiv salda izvoda.\n")

    for uid in uids[-koliko:]:
        status, msg_data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not msg_data or msg_data[0] is None:
            continue
        msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
        print(f"=== UID {uid.decode()}: {msg['Subject']!r} ({msg['Date']}) ===")

        for part in msg.iter_attachments():
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                text = payload.decode("cp1250", errors="replace")

            izvod = parse_statement(text, config.get("credit_type_codes"))
            uplate, preskoceno = izvod["uplate"], izvod["isplate"]
            stanje = "saldo se poklapa" if izvod["saldo_ok"] else f"NE VALJA: {izvod['poruka']}"
            print(f"  Prilog: {len(uplate)} uplata, {len(preskoceno)} isplata  ({stanje})")

            for t in uplate:
                print(f"    UPLATA    {t['amount']:10.2f} EUR  {t['date']}  "
                      f"{t['name']}  |  {t['description'][:60]}")
                if puni_redak:
                    print(f"      {t['raw_line']}")
                if maska:
                    print(f"      {maskiraj(t['raw_line'])}")

            for p in preskoceno:
                print(f"    ISPLATA   {p['amount']:10.2f} EUR  {p['date']}  "
                      f"{p['name']}  |  {p['description'][:60]}")
                if puni_redak:
                    print(f"      {p['raw_line']}")
                if maska:
                    print(f"      {maskiraj(p['raw_line'])}")
        print()



def main():
    parser = argparse.ArgumentParser(description="Dijagnostika za bank_solo.")
    parser.add_argument("--izvod", action="store_true",
                        help="Pokaži kako se transakcije iz stvarnih izvoda klasificiraju")
    parser.add_argument("--koliko", type=int, default=3,
                        help="Koliko zadnjih izvoda pregledati (uz --izvod, default 3)")
    parser.add_argument("--puni-redak", action="store_true",
                        help="Ispiši i cijeli redak izvoda (sadrži IBAN i ime uplatitelja)")
    parser.add_argument("--maska", action="store_true",
                        help="Ispiši oblik retka sa zamijenjenim znakovima "
                             "(znamenke -> 9, slova -> A) - pokazuje raspored polja "
                             "bez ijednog tvog podatka, sigurno za dijeljenje")
    args = parser.parse_args()

    config = load_config()
    imap = connect(config)
    try:
        if args.izvod:
            diagnose_statements(config, imap, args.koliko, args.puni_redak, args.maska)
        else:
            diagnose_folder(config, imap)
    finally:
        imap.logout()


if __name__ == "__main__":
    main()
