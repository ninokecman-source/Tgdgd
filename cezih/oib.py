"""Provjera OIB-a (ISO 7064, MOD 11,10) - da pogrešan OIB ne stigne do CEZIH-a."""


def je_ispravan(oib: str) -> bool:
    if not isinstance(oib, str) or len(oib) != 11 or not oib.isdigit():
        return False
    ostatak = 10
    for znamenka in oib[:10]:
        ostatak = (int(znamenka) + ostatak) % 10 or 10
        ostatak = (ostatak * 2) % 11
    kontrolna = (11 - ostatak) % 10
    return kontrolna == int(oib[10])
