"""
Čita bankovne izvode (Erste banka) koji stižu na Zoho mail, prepoznaje
uplate polaznika Emmett tečajeva (usporedbom s Excel tablicama prijava),
i za svaku uplatu izdaje Solo ponudu (nefiskaliziranu) na stvarno
uplaćeni iznos. Iznos se automatski zbraja u "Payment Received" koloni
odgovarajućeg Excel retka.

Namijenjena pokretanju preko crona, isto kao zoho_to_excel.py i
cliniko_solo/sync.py. Svaka transakcija se obrađuje točno jednom (SQLite
stanje u state_db_path).

Pokretanje:
    python3 sync.py
"""

import email
import imaplib
import json
import sys
from email import policy
from pathlib import Path

from registrants import add_payment, find_matching_registrant, load_registrants
from solo_client import SoloAPIError, SoloClient
from state import StateStore
from statement_parser import parse_statement

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Nema {CONFIG_PATH}. Kopiraj config.example.json u config.json i popuni podatke."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def extract_statement_attachments(msg) -> list:
    """Vrati listu tekstualnih sadržaja svih priloga koji izgledaju kao
    bankovni izvod (bilo koja ekstenzija - format se prepoznaje po
    sadržaju, ne po nazivu)."""
    texts = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = payload.decode("cp1250", errors="replace")
        texts.append(text)
    return texts


def resolve_description(config: dict, amount: float, course_code: str):
    """Odluči koji opis staviti na ponudi: akontacija (ako iznos odgovara
    deposit_amount) ili naziv tog konkretnog tečaja. tip_usluge je uvijek
    ista (šira) kategorija - vrati None ako se kod tečaja ne može
    pronaći u course_description_map."""
    deposit_amount = config.get("deposit_amount")
    if deposit_amount is not None and abs(amount - deposit_amount) < 0.01:
        return config["deposit_description"]

    return config.get("course_description_map", {}).get(course_code)


def process_transaction(tx, registrants, config, solo, state) -> bool:
    """Vrati True ako je transakcija obrađena (uparena i poslana), False
    ako nije uparena (preskočena, treba ručna provjera)."""
    if state.is_transaction_processed(tx["ref_id"]):
        return False

    registrant = find_matching_registrant(tx["raw_line"], registrants)
    if registrant is None:
        print(f"[!] Neuparena uplata {tx['amount']:.2f} EUR ({tx['date']}, ref {tx['ref_id']}) "
              f"- nijedno ime polaznika nije pronađeno u retku, treba ručna provjera.")
        return False

    full_name = f"{registrant['first_name']} {registrant['last_name']}".strip()
    napomene = f"{registrant['course_code']} - {registrant['location']}".strip(" -")

    opis = resolve_description(config, tx["amount"], registrant["course_code"])
    if opis is None:
        print(f"[!] Uplata {tx['amount']:.2f} EUR za {full_name} uparena, ali kod tečaja "
              f"{registrant['course_code']!r} nema definiran opis u "
              f"course_description_map - preskačem, treba ručna provjera.")
        return False

    stavke = [{
        "opis": opis,
        "cijena": tx["amount"],
        "kolicina": 1,
        "porez_stopa": config["solo_default_tax_rate"],
    }]

    try:
        ponuda = solo.create_ponuda(
            tip_kupca=config["solo_tip_kupca"],
            tip_usluge=config["solo_tip_usluge"],
            nacin_placanja=config["solo_nacin_placanja"],
            kupac_naziv=full_name,
            kupac_adresa=registrant.get("address") or None,
            kupac_oib=registrant.get("oib") or None,
            stavke=stavke,
            napomene=napomene,
        )
    except SoloAPIError as e:
        print(f"[GREŠKA] Solo ponuda za {full_name} ({tx['ref_id']}): {e}", file=sys.stderr)
        return False

    broj_ponude = ponuda.get("broj_ponude")
    new_total = add_payment(registrant["file_path"], registrant["row"], tx["amount"])

    state.mark_transaction_processed(tx["ref_id"], tx["amount"], full_name, broj_ponude)

    print(f"Uplata {tx['amount']:.2f} EUR -> {full_name} ({napomene}) "
          f"-> Solo ponuda {broj_ponude}, ukupno uplaćeno sad: {new_total:.2f} EUR")
    return True


def run():
    config = load_config()
    state = StateStore(config["state_db_path"])
    solo = SoloClient(api_token=config["solo_api_token"])

    imap = imaplib.IMAP4_SSL(config["imap_host"])
    imap.login(config["zoho_email"], config["zoho_app_password"])
    imap.select(config.get("imap_folder", "INBOX"))

    status, uid_data = imap.uid(
        "search", None, f'(FROM "{config["bank_sender"]}")'
    )
    if status != "OK":
        sys.exit(f"IMAP pretraga nije uspjela: {status}")

    uids = uid_data[0].split()
    new_uids = [uid.decode() for uid in uids if not state.is_mail_processed(uid.decode())]

    if not new_uids:
        print("Nema novih bankovnih izvoda.")
        imap.logout()
        state.close()
        return

    registrants = load_registrants(Path(config["excel_dir"]))
    print(f"Učitano {len(registrants)} polaznika iz Excel tablica.")

    processed_count = 0
    unmatched_count = 0

    for uid in new_uids:
        status, msg_data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not msg_data or msg_data[0] is None:
            continue

        msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
        attachments = extract_statement_attachments(msg)
        print(f"Mail UID {uid} ({msg['Subject']}): {len(attachments)} prilog(a)")

        for attachment_text in attachments:
            transactions = parse_statement(attachment_text)
            print(f"  Pronađeno {len(transactions)} transakcija u prilogu.")
            for tx in transactions:
                if process_transaction(tx, registrants, config, solo, state):
                    processed_count += 1
                elif not state.is_transaction_processed(tx["ref_id"]):
                    unmatched_count += 1

        state.mark_mail_processed(uid)

    imap.logout()
    state.close()

    print(f"\nGotovo. Poslano {processed_count} novih Solo ponuda, "
          f"{unmatched_count} uplata nije uparen s poznatim polaznikom.")


if __name__ == "__main__":
    run()
