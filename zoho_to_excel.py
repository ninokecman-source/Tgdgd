"""
Čita prijave (mailove) sa Zoho Mail računa i upisuje podatke prijavljenih
polaznika u Excel tablicu, po lokaciji (npr. Split / Zagreb).

Pokretanje:
    python zoho_to_excel.py

Postavke se čitaju iz config.json (napravi ga iz config.example.json).
"""

import imaplib
import email
from email import policy
import json
import re
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook

CONFIG_PATH = Path(__file__).with_name("config.json")

COLUMNS = [
    "Ime i prezime",
    "Ulica",
    "Grad",
    "Poštanski broj",
    "Telefon",
    "Email",
    "OIB",
]

# Tekstualne oznake polja onako kako se pojavljuju u tijelu maila.
FIELD_LABELS = {
    "ime_prezime": "Ime i prezime",
    "email": "Email",
    "mjesto_postanski": "Mjesto stanovanja i poštanski broj",
    "ulica": "Adresa",
    "oib": "OIB",
    "telefon": "Br. Tel",
}

POSTAL_CODE_RE = re.compile(r"\b\d{5}\b")
TAG_RE = re.compile(r"<[^<]+?>")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Nedostaje {CONFIG_PATH}. Kopiraj config.example.json u config.json "
            "i popuni svoje podatke."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_state(state_path: Path) -> set:
    if state_path.exists():
        with open(state_path, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_state(state_path: Path, processed: set) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(sorted(processed), f, ensure_ascii=False, indent=2)


def get_plain_text(msg: email.message.EmailMessage) -> str:
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    content = body.get_content()
    if body.get_content_type() == "text/html":
        content = TAG_RE.sub("\n", content)
        content = (
            content.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )
    return content


def find_identifier_line(lines: list) -> str:
    for line in lines:
        if line.strip().lower().startswith("prijava"):
            continue
        if " - " in line or re.search(r"-\s*\d{2}[.\-]", line):
            return line
    return lines[0] if lines else ""


def extract_value_after_label(lines: list, label: str) -> str:
    for i, line in enumerate(lines):
        if line.strip().startswith(label):
            for next_line in lines[i + 1:]:
                if next_line.strip():
                    return next_line.strip()
    return ""


def split_mjesto_postanski(value: str) -> tuple:
    match = POSTAL_CODE_RE.search(value)
    if not match:
        return value.strip(), ""
    postal_code = match.group(0)
    grad = (value[: match.start()] + value[match.end():]).strip()
    return grad, postal_code


def parse_application(text: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines()]
    non_empty = [ln for ln in lines if ln]

    identifier_line = find_identifier_line(non_empty)

    mjesto_raw = extract_value_after_label(lines, FIELD_LABELS["mjesto_postanski"])
    grad, postal_code = split_mjesto_postanski(mjesto_raw)

    return {
        "identifier_line": identifier_line,
        "Ime i prezime": extract_value_after_label(lines, FIELD_LABELS["ime_prezime"]),
        "Ulica": extract_value_after_label(lines, FIELD_LABELS["ulica"]),
        "Grad": grad,
        "Poštanski broj": postal_code,
        "Telefon": extract_value_after_label(lines, FIELD_LABELS["telefon"]),
        "Email": extract_value_after_label(lines, FIELD_LABELS["email"]),
        "OIB": extract_value_after_label(lines, FIELD_LABELS["oib"]),
    }


def match_location(identifier_line: str, instructor_name: str, locations: list):
    if instructor_name.lower() not in identifier_line.lower():
        return None
    for loc in locations:
        if re.search(rf"\b{re.escape(loc)}\b", identifier_line, re.IGNORECASE):
            return loc
    return None


def open_workbook(excel_path: Path, locations: list) -> Workbook:
    if excel_path.exists():
        wb = load_workbook(excel_path)
    else:
        wb = Workbook()
        wb.remove(wb.active)

    for loc in locations:
        if loc not in wb.sheetnames:
            ws = wb.create_sheet(loc)
            ws.append(COLUMNS)
    return wb


def append_row(wb: Workbook, sheet_name: str, data: dict) -> None:
    ws = wb[sheet_name]
    row = [data[col] for col in COLUMNS]
    ws.append(row)
    text_cols = {"Telefon", "OIB", "Poštanski broj"}
    new_row_idx = ws.max_row
    for col_idx, col_name in enumerate(COLUMNS, start=1):
        if col_name in text_cols:
            ws.cell(row=new_row_idx, column=col_idx).number_format = "@"


def main():
    config = load_config()
    state_path = Path(config.get("state_path", "processed_uids.json"))
    excel_path = Path(config["excel_path"])
    excel_path.parent.mkdir(parents=True, exist_ok=True)

    processed = load_state(state_path)

    imap = imaplib.IMAP4_SSL(config["imap_host"])
    imap.login(config["zoho_email"], config["zoho_app_password"])
    imap.select(config.get("imap_folder", "INBOX"))

    status, uid_data = imap.uid("search", None, f'(FROM "{config["sender_filter"]}")')
    if status != "OK":
        sys.exit(f"IMAP pretraga nije uspjela: {status}")

    uids = uid_data[0].split()
    new_uids = [uid.decode() for uid in uids if uid.decode() not in processed]

    if not new_uids:
        print("Nema novih mailova.")
        imap.logout()
        return

    wb = open_workbook(excel_path, config["locations"])
    added = 0

    for uid in new_uids:
        status, msg_data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not msg_data or msg_data[0] is None:
            continue

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw, policy=policy.default)
        text = get_plain_text(msg)
        parsed = parse_application(text)

        location = match_location(
            parsed["identifier_line"], config["instructor_name"], config["locations"]
        )

        if location:
            append_row(wb, location, parsed)
            added += 1
            print(f"Dodano ({location}): {parsed['Ime i prezime']}")
        else:
            print(f"Preskočeno (nije za {config['instructor_name']}): {parsed['identifier_line'][:80]}")

        processed.add(uid)

    wb.save(excel_path)
    save_state(state_path, processed)
    imap.logout()

    print(f"\nGotovo. Dodano {added} novih prijava u {excel_path}")


if __name__ == "__main__":
    main()
