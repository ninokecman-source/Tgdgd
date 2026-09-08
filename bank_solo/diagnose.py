"""
Dijagnostika za bank_solo.

Bez argumenata: zašto pretraga ne pronalazi mailove s bankovnim izvodima
u 'Izvodi' folderu.

    python3 diagnose.py

S --izvod: dohvati zadnje izvode i pokaži kako se svaka transakcija
klasificira (uplata / isplata / nepoznat kod). Time se provjerava jesu li
`credit_type_codes` u config.json ispravno podešeni - ako neka tvoja
stvarna uplata ovdje ispadne "nije među uplatama", treba dodati taj kod.

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


def diagnose_statements(config, imap, koliko: int, puni_redak: bool):
    folder = config.get("imap_folder", "INBOX")
    imap.select(f'"{folder}"')
    status, data = imap.uid("search", None, f'(FROM "{config["bank_sender"]}")')
    uids = data[0].split() if data and data[0] else []
    if not uids:
        print(f"Nema nijednog maila od {config['bank_sender']!r} u folderu {folder!r}.")
        return

    kodovi = config.get("credit_type_codes")
    print(f"Kodovi koji se trenutno smatraju uplatom: {kodovi or ['10 (default)']}\n")

    svi_kodovi = {}

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

            uplate, preskoceno = parse_statement(text, kodovi)
            print(f"  Prilog: {len(uplate)} uplata, {len(preskoceno)} preskočeno")

            for t in uplate:
                svi_kodovi.setdefault(t["type_code"], {"uplata": 0, "preskoceno": 0})
                svi_kodovi[t["type_code"]]["uplata"] += 1
                print(f"    UPLATA    kod {t['type_code']}  {t['amount']:10.2f} EUR  "
                      f"{t['date']}  ref {t['ref_id']}")
                if puni_redak:
                    print(f"      {t['raw_line']}")

            for p in preskoceno:
                svi_kodovi.setdefault(p["type_code"], {"uplata": 0, "preskoceno": 0})
                svi_kodovi[p["type_code"]]["preskoceno"] += 1
                iznos = f"{p['amount']:10.2f} EUR" if p["amount"] is not None else "         ?"
                print(f"    preskočeno kod {p['type_code']}  {iznos}  -> {p['razlog']}")
                if puni_redak:
                    print(f"      {p['raw_line']}")
        print()

    if svi_kodovi:
        print("=== Sažetak po kodu tipa transakcije ===")
        for kod in sorted(svi_kodovi):
            b = svi_kodovi[kod]
            print(f"  kod {kod}: {b['uplata']} uzeto kao uplata, {b['preskoceno']} preskočeno")
        print("\nAko je neka tvoja stvarna uplata gore označena kao preskočena,")
        print("dodaj njezin kod u \"credit_type_codes\" u bank_solo/config.json.")


def main():
    parser = argparse.ArgumentParser(description="Dijagnostika za bank_solo.")
    parser.add_argument("--izvod", action="store_true",
                        help="Pokaži kako se transakcije iz stvarnih izvoda klasificiraju")
    parser.add_argument("--koliko", type=int, default=3,
                        help="Koliko zadnjih izvoda pregledati (uz --izvod, default 3)")
    parser.add_argument("--puni-redak", action="store_true",
                        help="Ispiši i cijeli redak izvoda (sadrži IBAN i ime uplatitelja)")
    args = parser.parse_args()

    config = load_config()
    imap = connect(config)
    try:
        if args.izvod:
            diagnose_statements(config, imap, args.koliko, args.puni_redak)
        else:
            diagnose_folder(config, imap)
    finally:
        imap.logout()


if __name__ == "__main__":
    main()
