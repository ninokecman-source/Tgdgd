"""
Parsira Erste banka dnevni izvod (fiksno-formatirani tekstualni .wri prilog).

Format je proprietaran, redak po redak, svaki redak završava 3-znamenkastim
kodom tipa retka (900=zaglavlje, 903=račun, 905=transakcija, 907=saldo,
909/999=kraj). Kodiranje je cp1250.

Pozicije polja u transakcijskom (905) retku, izmjerene iz stvarnog izvoda:

    [0:2]      tip transakcije: "20" uplata, "10" isplata
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

SMJER: nosi ga dvoznamenkasti kod tipa transakcije - "20" je uplata,
"10" isplata. Predznak iznosa NE nosi smjer: u stvarnim izvodima i uplate
i isplate imaju '+'.

Redak sa saldom (907) sadrži, na fiksnim pozicijama:

    iznos #0  početni saldo
    iznos #3  ukupno isplata
    iznos #4  ukupno uplata
    iznos #5  završni saldo

Kako se smjer ne bi mogao krivo pročitati (a kriva ponuda u Solu se teško
popravlja), svaki izvod se PROVJERAVA protiv ta dva ukupna iznosa: zbroj
pročitanih uplata mora odgovarati ukupnim uplatama, a zbroj isplata
ukupnim isplatama. Ako se ne poklapa - npr. banka uvede novi kod tipa -
izvod se ne obrađuje nego se javi u logu, umjesto da se nešto krivo
proknjiži.
"""

import re

TRANSACTION_RE = re.compile(r"^\d{2}[A-Z]{2}\d")
AMOUNT_RE = re.compile(r"[+-]\d{15}")

DEFAULT_CREDIT_TYPE_CODES = ["20"]   # "20" = uplata, "10" = isplata

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
    """Iz 907 retka vrati {pocetni, zavrsni, ukupno_isplata, ukupno_uplata},
    ili None ako ga nema ili se iznosi ne slažu međusobno.

    Provjera 'početni - isplate + uplate = završni' potvrđuje da su polja
    pročitana s pravih mjesta; ako ne prolazi, raspored nije onakav kakav
    očekujemo i bolje je reći da salda nema nego se osloniti na krive
    brojeve."""
    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if not stripped.endswith("907"):
            continue
        iznosi = [int(m.group()) / 100 for m in AMOUNT_RE.finditer(stripped[:-3])]
        if len(iznosi) < 6:
            continue

        saldo = {
            "pocetni": iznosi[0],
            "ukupno_isplata": iznosi[3],
            "ukupno_uplata": iznosi[4],
            "zavrsni": iznosi[5],
        }
        ocekivani = saldo["pocetni"] - saldo["ukupno_isplata"] + saldo["ukupno_uplata"]
        if abs(ocekivani - saldo["zavrsni"]) > 0.01:
            return None
        return saldo
    return None


def parse_statement(text: str, credit_type_codes=None) -> dict:
    """Vrati dict s pročitanim izvodom:

        uplate         - lista ulaznih transakcija
        isplate        - lista izlaznih transakcija
        saldo_ok       - True ako se oba zbroja poklapaju sa saldom izvoda
        poruka         - objašnjenje ako se ne poklapa (inače prazno)

    Kad je saldo_ok False, pozivatelj NE SMIJE obraditi uplate iz ovog
    izvoda - znači da smjer ili raspored polja nisu ispravno pročitani.
    """
    credit_codes = set(credit_type_codes or DEFAULT_CREDIT_TYPE_CODES)

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
        # Nepoznat kod ide među isplate: tako se ne izdaje ponuda za nešto
        # što nismo prepoznali, a provjera salda ispod to ionako uhvati.
        (uplate if tx["type_code"] in credit_codes else isplate).append(tx)

    saldo = _parse_saldo(text)
    if saldo is None:
        return {
            "uplate": uplate,
            "isplate": isplate,
            "saldo_ok": False,
            "poruka": "u izvodu nema upotrebljivog retka sa saldom (907) - ne mogu "
                      "provjeriti jesu li transakcije ispravno pročitane",
        }

    zbroj_uplata = round(sum(abs(t["amount"]) for t in uplate), 2)
    zbroj_isplata = round(sum(abs(t["amount"]) for t in isplate), 2)

    neslaganja = []
    if abs(zbroj_uplata - saldo["ukupno_uplata"]) > 0.01:
        neslaganja.append(
            f"uplate: izvod kaže {saldo['ukupno_uplata']:.2f} EUR, "
            f"a pročitao sam {zbroj_uplata:.2f} EUR ({len(uplate)} transakcija)")
    if abs(zbroj_isplata - saldo["ukupno_isplata"]) > 0.01:
        neslaganja.append(
            f"isplate: izvod kaže {saldo['ukupno_isplata']:.2f} EUR, "
            f"a pročitao sam {zbroj_isplata:.2f} EUR ({len(isplate)} transakcija)")

    if neslaganja:
        kodovi = sorted({t["type_code"] for t in uplate + isplate})
        return {
            "uplate": uplate,
            "isplate": isplate,
            "saldo_ok": False,
            "poruka": ("ne poklapa se sa saldom izvoda - " + "; ".join(neslaganja) +
                       f". Kodovi tipa u izvodu: {kodovi}, kao uplate se broje "
                       f"{sorted(credit_codes)}"),
        }

    return {"uplate": uplate, "isplate": isplate, "saldo_ok": True, "poruka": ""}
