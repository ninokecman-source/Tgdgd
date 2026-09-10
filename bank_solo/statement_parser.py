"""
Parsira Erste banka dnevni izvod (fiksno-formatirani tekstualni .wri prilog).

Format je proprietaran, redak po redak, svaki redak završava 3-znamenkastim
kodom tipa retka (900=zaglavlje, 903=račun, 905=transakcija, 907=saldo,
909/999=kraj). Kodiranje je cp1250.

Pozicije polja u transakcijskom (905) retku, izmjerene iz stvarnog izvoda:

    [0:2]      tip transakcije (npr. "10", "20") - NE označava smjer!
    [2:23]     IBAN druge strane
    [36:81]    ime / naziv druge strane
    [81:176]   mjesto
    [176:184]  datum valute (YYYYMMDD)
    [184:192]  datum knjiženja
    [192:195]  "EUR"
    [210:226]  iznos s predznakom (15 znamenki, u centima)
    [226:242]  isti iznos, ponovljen
    [242:268]  poziv na broj platitelja
    [268:294]  poziv na broj primatelja
    [294:...]  opis plaćanja
    zadnji token u retku = jedinstvena referencija transakcije

SMJER: određuje ga predznak iznosa ('+' uplata, '-' isplata). Dvoznamenkasti
kod tipa transakcije NE govori ništa o smjeru - potvrđeno na stvarnom izvodu
gdje su obje transakcije s kodom "20" bile uplate.

Kako se smjer ne bi mogao krivo pročitati (a kriva ponuda u Solu se teško
popravlja), svaki izvod se PROVJERAVA protiv vlastitog salda: razlika
završnog i početnog salda iz 907 retka mora se poklopiti sa zbrojem
pročitanih uplata umanjenim za isplate. Ako se ne poklapa, izvod se ne
obrađuje - bolje stati i javiti nego izdati krivi dokument.
"""

import re

TRANSACTION_RE = re.compile(r"^\d{2}[A-Z]{2}\d")
AMOUNT_RE = re.compile(r"[+-]\d{15}")

POS_TYPE_CODE = (0, 2)
POS_IBAN = (2, 23)
POS_NAME = (36, 81)
POS_PLACE = (81, 176)
POS_DATE = (176, 184)
POS_AMOUNT = (210, 226)
POS_REF_PAYER = (242, 268)
POS_REF_PAYEE = (268, 294)
POS_DESCRIPTION = 294


def _polje(body: str, raspon: tuple) -> str:
    start, kraj = raspon
    return body[start:kraj].strip() if len(body) > start else ""


def _parse_transakcija(body: str) -> dict:
    amount_text = _polje(body, POS_AMOUNT)
    if not AMOUNT_RE.fullmatch(amount_text):
        # redak ne odgovara očekivanom rasporedu - nađi prvi iznos bilo gdje
        match = AMOUNT_RE.search(body)
        if not match:
            return None
        amount_text = match.group()

    opis = body[POS_DESCRIPTION:] if len(body) > POS_DESCRIPTION else ""
    opis = re.split(r"\s{5,}", opis.strip())[0] if opis.strip() else ""

    tokens = body.split()
    return {
        "amount": int(amount_text) / 100,
        "type_code": _polje(body, POS_TYPE_CODE),
        "iban": _polje(body, POS_IBAN),
        "name": _polje(body, POS_NAME),
        "place": _polje(body, POS_PLACE),
        "date": _polje(body, POS_DATE),
        "description": opis,
        "ref_payer": _polje(body, POS_REF_PAYER),
        "ref_payee": _polje(body, POS_REF_PAYEE),
        "ref_id": tokens[-1] if tokens else "",
        "raw_line": body,
    }


def _parse_saldo(text: str):
    """Iz 907 retka vrati (početni_saldo, završni_saldo), ili None ako ga
    nema. Prvi iznos u retku je početni, zadnji je završni saldo."""
    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if not stripped.endswith("907"):
            continue
        iznosi = [int(m.group()) / 100 for m in AMOUNT_RE.finditer(stripped[:-3])]
        if len(iznosi) >= 2:
            return iznosi[0], iznosi[-1]
    return None


def parse_statement(text: str) -> dict:
    """Vrati dict s pročitanim izvodom:

        uplate         - lista ulaznih transakcija (predznak '+')
        isplate        - lista izlaznih transakcija (predznak '-')
        saldo_ok       - True ako se promet poklapa sa saldom izvoda
        poruka         - objašnjenje ako se ne poklapa (inače prazno)

    Kad je saldo_ok False, pozivatelj NE SMIJE obraditi uplate iz ovog
    izvoda - znači da raspored polja ili smjer nisu ispravno pročitani.
    """
    uplate, isplate = [], []

    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if len(stripped) < 3 or stripped[-3:] != "905":
            continue

        body = stripped[:-3].rstrip()
        if not TRANSACTION_RE.match(body):
            continue

        tx = _parse_transakcija(body)
        if tx is None:
            continue
        (uplate if tx["amount"] >= 0 else isplate).append(tx)

    saldo = _parse_saldo(text)
    if saldo is None:
        return {
            "uplate": uplate,
            "isplate": isplate,
            "saldo_ok": False,
            "poruka": "u izvodu nema retka sa saldom (907) - ne mogu provjeriti "
                      "jesu li transakcije ispravno pročitane",
        }

    pocetni, zavrsni = saldo
    promet_izvoda = round(zavrsni - pocetni, 2)
    promet_procitan = round(sum(t["amount"] for t in uplate + isplate), 2)

    if abs(promet_izvoda - promet_procitan) > 0.01:
        return {
            "uplate": uplate,
            "isplate": isplate,
            "saldo_ok": False,
            "poruka": (
                f"promet se ne poklapa sa saldom izvoda: saldo kaže "
                f"{promet_izvoda:.2f} EUR ({pocetni:.2f} -> {zavrsni:.2f}), a iz "
                f"transakcija sam pročitao {promet_procitan:.2f} EUR "
                f"({len(uplate)} uplata, {len(isplate)} isplata)"
            ),
        }

    return {"uplate": uplate, "isplate": isplate, "saldo_ok": True, "poruka": ""}
