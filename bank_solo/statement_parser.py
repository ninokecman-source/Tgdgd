"""
Parsira Erste banka dnevni izvod (fiksno-formatirani tekstualni .wri prilog)
i vraća listu ulaznih (kreditnih) transakcija.

Format je proprietaran, redak po redak, svaki redak završava 3-znamenkastim
kodom tipa retka (900=zaglavlje, 903=račun, 905=transakcija, 907=saldo,
909/999=kraj). Transakcijski redak počinje s "10" + IBAN pošiljatelja, i
sadrži iznos kao 15-znamenkasti broj s predznakom (u centima), dva datuma
(YYYYMMDD) prije "EUR", te jedinstvenu referencu transakcije na kraju retka
(koristi se za sprečavanje dupliciranja).

Ime uplatitelja i opis plaćanja NISU parsirani na točnu poziciju (format
za to nije dovoljno pouzdano potvrđen) - umjesto toga se cijeli tekst
retka (`raw_line`) koristi za pretragu poznatih imena polaznika.
"""

import re

TRANSACTION_RE = re.compile(r"^10[A-Z]{2}\d")
AMOUNT_RE = re.compile(r"[+-]\d{15}")
DATE_RE = re.compile(r"(\d{8})(\d{8})EUR")


def parse_statement(text: str) -> list:
    """Vrati listu dictova {amount, date, ref_id, raw_line} za sve ULAZNE
    (kreditne, predznak '+') transakcije u izvodu."""
    transactions = []

    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if len(stripped) < 3:
            continue

        record_type = stripped[-3:]
        if record_type != "905":
            continue

        body = stripped[:-3].rstrip()
        if not TRANSACTION_RE.match(body):
            continue

        amounts = AMOUNT_RE.findall(body)
        if not amounts:
            continue

        first_amount = amounts[0]
        if first_amount.startswith("-"):
            continue  # izlazna (debitna) transakcija - preskoči

        amount = int(first_amount) / 100

        date_match = DATE_RE.search(body)
        date = date_match.group(1) if date_match else ""

        tokens = body.split()
        ref_id = tokens[-1] if tokens else ""

        transactions.append({
            "amount": amount,
            "date": date,
            "ref_id": ref_id,
            "raw_line": body,
        })

    return transactions
