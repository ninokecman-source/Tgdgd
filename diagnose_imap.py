"""
Dijagnostika: zašto pretraga ne pronalazi 2026. mailove.
Provjerava odvojeno pošiljatelja, datum, i folder.

Pokretanje:
    python3 diagnose_imap.py
"""

import imaplib
import email
from email import policy
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

imap = imaplib.IMAP4_SSL(config["imap_host"])
imap.login(config["zoho_email"], config["zoho_app_password"])

print("=== Dostupni folderi na računu ===")
status, folders = imap.list()
for f in folders:
    print(" ", f.decode(errors="replace"))

folder = config.get("imap_folder", "INBOX")
imap.select(folder)
print(f"\n=== Pretraga u folderu: {folder} ===")

status, data = imap.uid("search", None, f'(FROM "{config["sender_filter"]}")')
all_from_sender = data[0].split()
print(f"Ukupno mailova od {config['sender_filter']} (bez obzira na datum): {len(all_from_sender)}")

status, data = imap.uid("search", None, f'(SINCE "01-Jan-2026")')
all_since_2026 = data[0].split()
print(f"Ukupno mailova od 01-Jan-2026 (bez obzira na pošiljatelja): {len(all_since_2026)}")

status, data = imap.uid("search", None, f'(FROM "{config["sender_filter"]}" SINCE "01-Jan-2026")')
combined = data[0].split()
print(f"Kombinirano (pošiljatelj + od 2026.): {len(combined)}")

print(f"\n=== Zadnjih 5 mailova od {config['sender_filter']} (bilo koji datum) - njihov stvarni datum slanja ===")
for uid in all_from_sender[-5:]:
    status, msg_data = imap.uid("fetch", uid, "(RFC822.HEADER)")
    if status != "OK" or not msg_data or msg_data[0] is None:
        continue
    msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
    print(f"  UID {uid.decode()}: Date={msg['Date']!r}  Subject={msg['Subject']!r}")

imap.logout()
