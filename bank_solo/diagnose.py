"""
Dijagnostika: zašto pretraga ne pronalazi mailove s bankovnim izvodima u
'Izvodi' folderu.

Pokretanje:
    python3 diagnose.py
"""

import email
import imaplib
import json
from email import policy
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

imap = imaplib.IMAP4_SSL(config["imap_host"])
imap.login(config["zoho_email"], config["zoho_app_password"])

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
    print(f"  UID {uid.decode()}: From={msg['From']!r}  Date={msg['Date']!r}  Subject={msg['Subject']!r}")

print(f"\n=== Pretraga FROM \"{config['bank_sender']}\" ===")
status, data = imap.uid("search", None, f'(FROM "{config["bank_sender"]}")')
matched_uids = data[0].split() if data and data[0] else []
print(f"Pronađeno: {len(matched_uids)} -> {matched_uids}")

imap.logout()
