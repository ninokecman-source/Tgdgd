"""
Dohvaća OIB polaznika izravno iz njegove izvorne Zoho prijave (mail od
prijava@emmett-hr.com), po email adresi polaznika - OIB se ne sprema
trajno u Excel (predložak nema stupac za to), samo se dohvati kad
zatreba za Solo ponudu.

Pretražuje INBOX i sve podfoldere unutar course_folder_roots (Split,
Zagreb...), isto kao glavna Zoho skripta - koristi identičan IMAP UTF-7
dekoder za nazive foldera.
"""

import base64
import re

OIB_LABEL = "OIB / Personal Identification Number"
OIB_RE = re.compile(r"\b\d{11}\b")
FOLDER_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+"(?P<name>.*)"$')
TAG_RE = re.compile(r"<[^<]+?>")


def imap_utf7_decode(s: str) -> str:
    res = []
    b64_chars = ""
    in_b64 = False
    for ch in s:
        if not in_b64:
            if ch == "&":
                in_b64 = True
                b64_chars = ""
            else:
                res.append(ch)
        else:
            if ch == "-":
                if b64_chars == "":
                    res.append("&")
                else:
                    padded = b64_chars.replace(",", "/")
                    padded += "=" * (-len(padded) % 4)
                    res.append(base64.b64decode(padded).decode("utf-16-be"))
                in_b64 = False
            else:
                b64_chars += ch
    if in_b64 and b64_chars:
        padded = b64_chars.replace(",", "/")
        padded += "=" * (-len(padded) % 4)
        res.append(base64.b64decode(padded).decode("utf-16-be"))
    return "".join(res)


def discover_registration_folders(imap, roots: list) -> list:
    """Vrati listu sirovih naziva foldera: INBOX + sve unutar roots
    (Split, Zagreb, i njihovi podfolderi)."""
    status, data = imap.list()
    if status != "OK":
        return ["INBOX"]

    folders = ["INBOX"]
    for line in data:
        text = line.decode("utf-8", errors="replace")
        m = FOLDER_LIST_RE.match(text)
        if not m:
            continue
        raw_name = m.group("name")
        decoded_name = imap_utf7_decode(raw_name)
        for root in roots:
            if decoded_name == root or decoded_name.startswith(root + "/"):
                folders.append(raw_name)
                break
    return folders


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


def extract_oib_from_text(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith(OIB_LABEL):
            for next_line in lines[i + 1:]:
                if next_line.strip():
                    match = OIB_RE.search(next_line)
                    return match.group(0) if match else ""
    return ""


def find_oib(imap, sender_filter: str, folders: list, registrant_email: str) -> str:
    """Pretraži zadane foldere za prijavu koja u tijelu sadrži
    registrant_email, i vrati OIB iz nje (prazan string ako nije
    pronađen)."""
    import email
    from email import policy

    if not registrant_email:
        return ""

    for raw_folder in folders:
        status, _ = imap.select(f'"{raw_folder}"')
        if status != "OK":
            continue

        status, uid_data = imap.uid(
            "search", None,
            f'(FROM "{sender_filter}" BODY "{registrant_email}")',
        )
        if status != "OK" or not uid_data or not uid_data[0]:
            continue

        uids = uid_data[0].split()
        for uid in uids:
            status, msg_data = imap.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
            text = get_plain_text(msg)
            oib = extract_oib_from_text(text)
            if oib:
                return oib

    return ""
