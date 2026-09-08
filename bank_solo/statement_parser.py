"""
Parsira Erste banka dnevni izvod (fiksno-formatirani tekstualni .wri prilog)
i vraća listu ULAZNIH (kreditnih) transakcija - dakle samo uplate, nikad
isplate.

Format je proprietaran, redak po redak, svaki redak završava 3-znamenkastim
kodom tipa retka (900=zaglavlje, 903=račun, 905=transakcija, 907=saldo,
909/999=kraj). Transakcijski redak počinje s dvoznamenkastim kodom tipa
transakcije + IBAN druge strane, i sadrži iznos kao 15-znamenkasti broj s
predznakom (u centima), dva datuma (YYYYMMDD) prije "EUR", te jedinstvenu
referencu transakcije na kraju retka (koristi se za sprečavanje
dupliciranja).

Smjer transakcije (uplata vs isplata) se određuje po DVA uvjeta, i oba
moraju vrijediti da bi se redak uzeo kao uplata:

1. dvoznamenkasti kod tipa transakcije mora biti među `credit_type_codes`
   (podesivo u config.json, po defaultu samo "10"),
2. iznos ne smije imati minus predznak.

Namjerno je strogo: nepoznat kod se preskače umjesto da se pretpostavi da
je uplata. Kriva pretpostavka ovdje znači izdanu Solo ponudu za tuđu
isplatu, što se teško popravlja - dok preskočena uplata samo znači da će
se izdati ručno. Sve preskočeno se vraća u `skipped` da se vidi u logu.

Ime uplatitelja i opis plaćanja NISU parsirani na točnu poziciju (format
za to nije dovoljno pouzdano potvrđen) - umjesto toga se cijeli tekst
retka (`raw_line`) koristi za pretragu poznatih imena polaznika.
"""

import re

TRANSACTION_RE = re.compile(r"^(?P<code>\d{2})[A-Z]{2}\d")
AMOUNT_RE = re.compile(r"[+-]\d{15}")
DATE_RE = re.compile(r"(\d{8})(\d{8})EUR")

# Kod tipa transakcije koji označava odobrenje (uplatu na račun).
DEFAULT_CREDIT_TYPE_CODES = ["10"]


def parse_statement(text: str, credit_type_codes=None) -> tuple:
    """Vrati (uplate, preskoceno):

    - `uplate`: lista dictova {amount, date, ref_id, type_code, raw_line}
      za transakcije pozitivno prepoznate kao uplate,
    - `preskoceno`: lista dictova {razlog, type_code, amount, raw_line} za
      transakcijske retke koji nisu uzeti kao uplata (isplate i nepoznati
      kodovi) - da se u logu vidi što je ispušteno i zašto.
    """
    credit_codes = set(credit_type_codes or DEFAULT_CREDIT_TYPE_CODES)

    uplate = []
    preskoceno = []

    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if len(stripped) < 3:
            continue

        if stripped[-3:] != "905":
            continue

        body = stripped[:-3].rstrip()
        match = TRANSACTION_RE.match(body)
        if not match:
            continue

        type_code = match.group("code")

        amounts = AMOUNT_RE.findall(body)
        if not amounts:
            preskoceno.append({
                "razlog": "iznos nije prepoznat",
                "type_code": type_code,
                "amount": None,
                "raw_line": body,
            })
            continue

        first_amount = amounts[0]
        amount = int(first_amount) / 100

        if first_amount.startswith("-"):
            preskoceno.append({
                "razlog": "isplata (minus predznak)",
                "type_code": type_code,
                "amount": amount,
                "raw_line": body,
            })
            continue

        if type_code not in credit_codes:
            preskoceno.append({
                "razlog": f"kod tipa {type_code} nije među uplatama {sorted(credit_codes)}",
                "type_code": type_code,
                "amount": amount,
                "raw_line": body,
            })
            continue

        date_match = DATE_RE.search(body)
        date = date_match.group(1) if date_match else ""

        tokens = body.split()
        ref_id = tokens[-1] if tokens else ""

        uplate.append({
            "amount": amount,
            "date": date,
            "ref_id": ref_id,
            "type_code": type_code,
            "raw_line": body,
        })

    return uplate, preskoceno
