"""
Čita prijave (mailove) sa Zoho Mail računa i upisuje podatke polaznika u
Excel tablicu po uzoru na Emmett Technique Instructor Administration Sheet.

Za svaku kombinaciju (kod tečaja + grad održavanja) postoji zasebna .xlsx
datoteka, npr. "Modul 1&2 Split.xlsx". Nova prijava se dodaje kao novi red
u tablicu polaznika te datoteke.

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
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

CONFIG_PATH = Path(__file__).with_name("config.json")

# --- Predložak: struktura Emmett administrativne tablice -------------------

PARTICIPANT_HEADERS = [
    "First name",
    "Last Name",
    "Street ",
    "City/ Town ",
    "State/  Province",
    "Post/Zip Code ",
    "Email Address",
    "Mobile Ph",
    "Country",
    "New (N) or Revised (R) ",
    "Payment Received",
    "NOTES",
]

FIRST_PARTICIPANT_ROW = 10
LAST_PARTICIPANT_ROW = 28  # 19 redova (brojevi 1-19)
TOTALS_ROW = 29  # red s '=SUM(...)' formulom, pomiče se ako se doda red

EUR_FORMAT = '_ [$€-2]\\ * #,##0.00_ ;_ [$€-2]\\ * \\-#,##0.00_ ;_ [$€-2]\\ * "-"??_ ;_ @_ '
PHONE_FORMAT = "@"

FIELD_LABELS = {
    "ime_prezime": "Ime i prezime",
    "email": "Email",
    "mjesto_postanski": "Mjesto stanovanja i poštanski broj",
    "ulica": "Adresa",
    "telefon": "Br. Tel",
}

POSTAL_CODE_RE = re.compile(r"\b\d{5}\b")
DATE_RE = re.compile(r"\d{1,2}\.\s*-?\s*\d{0,2}\.?\s*\d{1,2}\.\s*\d{4}\.?")
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


def get_plain_text(msg) -> str:
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


def split_first_last_name(full_name: str) -> tuple:
    parts = full_name.strip().split(maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return parts[0], ""
    return "", ""


def parse_application(text: str) -> dict:
    lines = [ln.strip() for ln in text.splitlines()]
    non_empty = [ln for ln in lines if ln]

    identifier_line = find_identifier_line(non_empty)

    mjesto_raw = extract_value_after_label(lines, FIELD_LABELS["mjesto_postanski"])
    grad, postal_code = split_mjesto_postanski(mjesto_raw)

    full_name = extract_value_after_label(lines, FIELD_LABELS["ime_prezime"])
    first_name, last_name = split_first_last_name(full_name)

    return {
        "identifier_line": identifier_line,
        "First name": first_name,
        "Last Name": last_name,
        "Street ": extract_value_after_label(lines, FIELD_LABELS["ulica"]),
        "City/ Town ": grad,
        "Post/Zip Code ": postal_code,
        "Email Address": extract_value_after_label(lines, FIELD_LABELS["email"]),
        "Mobile Ph": extract_value_after_label(lines, FIELD_LABELS["telefon"]),
    }


def extract_location(identifier_line: str, course_code: str) -> str:
    """Grad se nalazi između koda tečaja i datuma u retku, npr.
    'EMMET - MODUL 1&2 - Split -05.-06.09.2026. - Nino Kecman' -> 'Split'.
    Radi za bilo koji grad, ne samo unaprijed poznati popis."""
    code_match = re.search(re.escape(course_code), identifier_line, re.IGNORECASE)
    if not code_match:
        return ""
    date_match = DATE_RE.search(identifier_line)
    end = code_match.end()
    stop = date_match.start() if date_match else len(identifier_line)
    return identifier_line[end:stop].strip(" -\t")


def match_course_and_location(identifier_line: str, instructor_name: str,
                               course_codes: list):
    if instructor_name.lower() not in identifier_line.lower():
        return None, None

    course_code = None
    for code in sorted(course_codes, key=len, reverse=True):
        if code.lower() in identifier_line.lower():
            course_code = code
            break

    if not course_code:
        return None, None

    location = extract_location(identifier_line, course_code)
    if not location:
        return None, None

    return course_code, location


def extract_dates(identifier_line: str) -> str:
    match = DATE_RE.search(identifier_line)
    return match.group(0) if match else ""


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", name).strip()


# --- Građenje / popunjavanje Excel predloška --------------------------------


def build_course_workbook(course_code: str, location: str, dates: str,
                           instructor: str, currency: str = "eur") -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "podaci"

    ws["B1"] = "EMMETT  TECHNIQUE  INSTRUCTOR ADMINISTRATION SHEET"
    ws["B1"].font = Font(bold=True, size=14)
    ws["M1"] = "=NOW()"
    ws["M1"].number_format = "m/d/yy h:mm"

    ws["B4"] = "COURSE/MOD"
    ws["C4"] = course_code
    ws["J4"] = "Instructor"
    ws["M4"] = instructor

    ws["B5"] = "LOCATION"
    ws["C5"] = location
    ws["J5"] = "Venue"
    ws["M5"] = ""  # popunjava se ručno

    ws["B6"] = "DATES"
    ws["C6"] = dates
    ws["J6"] = "Currency"
    ws["M6"] = currency

    ws["L7"] = "Table Totals"
    ws["L7"].number_format = EUR_FORMAT

    ws.merge_cells("C4:I4")
    ws.merge_cells("C5:I5")
    ws.merge_cells("C6:I6")
    ws.merge_cells("J4:L4")
    ws.merge_cells("J5:L5")
    ws.merge_cells("J6:L6")
    ws.merge_cells("M4:N4")
    ws.merge_cells("M5:N5")
    ws.merge_cells("M6:N6")

    for col_idx, header in enumerate(PARTICIPANT_HEADERS, start=2):  # B..M
        cell = ws.cell(row=9, column=col_idx, value=header)
        cell.font = Font(bold=True)
    ws["A9"] = None

    for row in range(FIRST_PARTICIPANT_ROW, LAST_PARTICIPANT_ROW + 1):
        ws.cell(row=row, column=1, value=row - FIRST_PARTICIPANT_ROW + 1)
        ws.cell(row=row, column=9).number_format = PHONE_FORMAT  # Mobile Ph
        ws.cell(row=row, column=12).number_format = '#,##0.00\\ "€"'  # Payment

    write_totals_formulas(ws, TOTALS_ROW)

    widths = {
        "A": 5.5, "B": 27, "C": 28, "D": 40, "E": 30, "F": 18, "G": 19,
        "H": 55, "I": 22, "J": 25, "K": 14, "L": 22, "M": 40,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    return wb


def write_totals_formulas(ws, totals_row: int) -> None:
    last_row = totals_row - 1
    ws.cell(row=totals_row, column=14,
            value=f"=SUM(L{FIRST_PARTICIPANT_ROW}:L{last_row})").number_format = "0.00"

    ws.cell(row=totals_row + 1, column=10, value="Total Income")
    c = ws.cell(row=totals_row + 1, column=12,
                value=f"=SUM(L{FIRST_PARTICIPANT_ROW}:L{totals_row})")
    c.number_format = '#,##0.00\\ "€"'

    ws.cell(row=totals_row + 2, column=10, value="VAT")
    ws.cell(row=totals_row + 2, column=11, value=0)
    c = ws.cell(row=totals_row + 2, column=12, value=f"=L{totals_row + 1}/119*K{totals_row + 2}")
    c.number_format = '#,##0.00\\ "€"'

    ws.cell(row=totals_row + 3, column=10, value="Income minus VAT x%")
    c = ws.cell(row=totals_row + 3, column=12, value=f"=L{totals_row + 1}-L{totals_row + 2}")
    c.number_format = '#,##0.00\\ "€"'

    ws.cell(row=totals_row + 4, column=10, value="Commission Emmett (15 %)")
    c = ws.cell(row=totals_row + 4, column=12, value=f"=L{totals_row + 3}*0.15")
    c.number_format = '#,##0.00\\ "€"'

    ws.cell(row=totals_row + 5, column=10, value="Commission Bord (5%)")
    c = ws.cell(row=totals_row + 5, column=12, value=f"=L{totals_row + 3}*0.05")
    c.number_format = '#,##0.00\\ "€"'

    ws.cell(row=totals_row + 6, column=10, value="Commission Rep. (5%)")
    c = ws.cell(row=totals_row + 6, column=12, value=f"=L{totals_row + 3}*0.05")
    c.number_format = '#,##0.00\\ "€"'

    ws.cell(row=totals_row + 7, column=10, value="Income ")
    c = ws.cell(row=totals_row + 7, column=12,
                value=f"=L{totals_row + 3}-L{totals_row + 4}-L{totals_row + 5}-L{totals_row + 6}")
    c.number_format = '#,##0.00\\ "€"'


def find_totals_row(ws) -> int:
    for row in range(FIRST_PARTICIPANT_ROW, ws.max_row + 2):
        if ws.cell(row=row, column=10).value == "Total Income":
            return row - 1
    return TOTALS_ROW


def next_participant_row(ws, totals_row: int) -> int:
    for row in range(FIRST_PARTICIPANT_ROW, totals_row):
        if ws.cell(row=row, column=2).value in (None, ""):
            return row
    return None  # nema slobodnog reda, treba proširiti tablicu


def expand_participant_table(ws, totals_row: int) -> int:
    """Umetne jedan dodatni red prije retka s ukupnim iznosima i vrati
    indeks novog (slobodnog) reda za polaznika."""
    vat_rate = ws.cell(row=totals_row + 2, column=11).value  # sačuvaj ručno uneseni PDV %

    ws.insert_rows(totals_row)
    new_row = totals_row
    last_number = ws.cell(row=new_row - 1, column=1).value or (new_row - FIRST_PARTICIPANT_ROW)
    ws.cell(row=new_row, column=1, value=last_number + 1)
    ws.cell(row=new_row, column=9).number_format = PHONE_FORMAT
    ws.cell(row=new_row, column=12).number_format = '#,##0.00\\ "€"'

    new_totals_row = find_totals_row(ws)
    write_totals_formulas(ws, new_totals_row)
    if vat_rate is not None:
        ws.cell(row=new_totals_row + 2, column=11, value=vat_rate)
    return new_row


def append_participant(ws, data: dict, totals_row: int) -> int:
    row = next_participant_row(ws, totals_row)
    if row is None:
        row = expand_participant_table(ws, totals_row)

    ws.cell(row=row, column=2, value=data["First name"])
    ws.cell(row=row, column=3, value=data["Last Name"])
    ws.cell(row=row, column=4, value=data["Street "])
    ws.cell(row=row, column=5, value=data["City/ Town "])
    postal = data["Post/Zip Code "]
    ws.cell(row=row, column=7, value=int(postal) if postal.isdigit() else postal)
    ws.cell(row=row, column=8, value=data["Email Address"])
    ws.cell(row=row, column=9, value=data["Mobile Ph"])
    ws.cell(row=row, column=9).number_format = PHONE_FORMAT
    ws.cell(row=row, column=10, value="Croatia")
    ws.cell(row=row, column=11, value="N")
    return row


def get_or_create_workbook(path: Path, course_code: str, location: str,
                            dates: str, instructor: str):
    if path.exists():
        wb = load_workbook(path)
        ws = wb["podaci"]
        if dates and ws["C6"].value != dates:
            ws["C6"] = dates
        return wb, ws
    wb = build_course_workbook(course_code, location, dates, instructor)
    return wb, wb["podaci"]


def main():
    config = load_config()
    state_path = Path(config.get("state_path", "processed_uids.json"))
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

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

    workbooks = {}  # (course_code, location) -> (path, wb, ws, totals_row)
    added = 0

    for uid in new_uids:
        status, msg_data = imap.uid("fetch", uid, "(RFC822)")
        if status != "OK" or not msg_data or msg_data[0] is None:
            continue

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw, policy=policy.default)
        text = get_plain_text(msg)
        parsed = parse_application(text)

        course_code, location = match_course_and_location(
            parsed["identifier_line"], config["instructor_name"],
            config["course_codes"],
        )

        if course_code and location:
            key = (course_code, location)
            if key not in workbooks:
                filename = sanitize_filename(f"{course_code} {location}") + ".xlsx"
                path = output_dir / filename
                dates = extract_dates(parsed["identifier_line"])
                wb, ws = get_or_create_workbook(
                    path, course_code, location, dates, config["instructor_name"]
                )
                totals_row = find_totals_row(ws)
                workbooks[key] = [path, wb, ws, totals_row]
            else:
                dates = extract_dates(parsed["identifier_line"])
                path, wb, ws, totals_row = workbooks[key]
                if dates and ws["C6"].value != dates:
                    ws["C6"] = dates

            path, wb, ws, totals_row = workbooks[key]
            row = append_participant(ws, parsed, totals_row)
            if row >= totals_row:
                totals_row = find_totals_row(ws)
                workbooks[key][3] = totals_row
            added += 1
            print(f"Dodano ({course_code} / {location}): "
                  f"{parsed['First name']} {parsed['Last Name']}")
        else:
            print(f"Preskočeno: {parsed['identifier_line'][:80]}")

        processed.add(uid)

    for path, wb, ws, _ in workbooks.values():
        wb.save(path)

    save_state(state_path, processed)
    imap.logout()

    print(f"\nGotovo. Dodano {added} novih prijava u {len(workbooks)} datoteka.")


if __name__ == "__main__":
    main()
