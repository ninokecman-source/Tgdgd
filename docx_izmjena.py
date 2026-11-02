"""
Sitne izmjene gotovog .docx dokumenta, bez pisanja dokumenta iznova.

Word dokument je zip s XML-om unutra. Kad treba samo upisati datum, broj
polaznika i par iznosa u obrazac koji je netko drugi složio, nema smisla
dokument crtati iznova - svaka bi se izmjena izgubila. Ovdje se dira samo
tekst na mjestima koja se izrijekom pronađu, a sve ostalo (pisma, zaglavlja,
rubovi tablica, logotip fakulteta) ostaje bajt po bajt kakvo je bilo.

Zato se i ne koristi XML parser: on bi cijeli dokument ispisao iznova i
usput preimenovao prostore imena. Umjesto toga se traže rasponi elemenata i
zamjenjuje se samo ono unutar njih.
"""

import re
from xml.sax.saxutils import escape

TEKST = re.compile(r"<w:t(?: [^>]*)?>(.*?)</w:t>", re.S)


def spanovi(xml: str, oznaka: str, od: int = 0, do: int = None) -> list:
    """[(početak, kraj)] svih elemenata <oznaka> na najvišoj razini reza.

    Dubina se broji jer tablica zna stajati u tablici; 'najviša razina'
    znači da se unutarnje preskaču."""
    do = len(xml) if do is None else do
    uzorak = re.compile(rf"<{oznaka}(?: [^>]*)?>|</{oznaka}>")
    nadjeno, dubina, poc = [], 0, 0
    for m in uzorak.finditer(xml, od, do):
        if m.group(0).startswith("</"):
            dubina -= 1
            if dubina == 0:
                nadjeno.append((poc, m.end()))
        else:
            if dubina == 0:
                poc = m.start()
            dubina += 1
    return nadjeno


def tekst(frag: str) -> str:
    """Čisti tekst elementa - sve što stoji u <w:t>."""
    spojeno = "".join(TEKST.findall(frag))
    return (spojeno.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("\xa0", " ")).strip()


def _prazni_tekst(frag: str) -> str:
    return TEKST.sub('<w:t xml:space="preserve"></w:t>', frag)


def postavi_tekst(paragraf: str, novi: str) -> str:
    """Paragraf s novim tekstom, u oblikovanju prvog njegovog dijela.

    Word tekst zna razbiti na više dijelova (<w:r>) i usred riječi, pa se
    novi tekst upisuje u prvi, a ostalima se tekst briše. Oblikovanje tog
    prvog dijela tako vrijedi za cijeli paragraf."""
    novi_xml = f'<w:t xml:space="preserve">{escape(novi)}</w:t>'
    dijelovi = spanovi(paragraf, "w:r")
    for poc, kraj in dijelovi:
        if TEKST.search(paragraf[poc:kraj]):
            prvi = TEKST.sub(novi_xml, paragraf[poc:kraj], count=1)
            ostatak = _prazni_tekst(paragraf[kraj:])
            return paragraf[:poc] + prvi + ostatak
    # paragraf bez teksta - treba mu dodati dio, s oblikovanjem iz <w:pPr>
    rpr = re.search(r"<w:rPr>.*?</w:rPr>", paragraf, re.S)
    run = f"<w:r>{rpr.group(0) if rpr else ''}{novi_xml}</w:r>"
    return paragraf[:-len("</w:p>")] + run + "</w:p>"


def postavi_celiju(celija: str, novi: str) -> str:
    """Isto, za ćeliju tablice: tekst ide u prvi paragraf, ostali se prazne."""
    paragrafi = spanovi(celija, "w:p")
    if not paragrafi:
        return celija
    poc, kraj = paragrafi[0]
    return (celija[:poc] + postavi_tekst(celija[poc:kraj], novi)
            + _prazni_tekst(celija[kraj:]))


def primijeni(xml: str, izmjene: list) -> str:
    """Izmjene kao [(početak, kraj, novi_xml)]. Idu od kraja prema početku,
    da raniji rasponi ostanu na svojim mjestima."""
    for poc, kraj, novo in sorted(izmjene, key=lambda i: -i[0]):
        xml = xml[:poc] + novo + xml[kraj:]
    return xml


def redovi_tablice(xml: str, span: tuple) -> list:
    return spanovi(xml, "w:tr", *span)


def celije_reda(xml: str, span: tuple) -> list:
    return spanovi(xml, "w:tc", *span)


def nadji_tablicu(xml: str, sadrzi: str):
    """Raspon prve tablice u kojoj se pojavljuje zadani tekst."""
    for span in spanovi(xml, "w:tbl"):
        if sadrzi in tekst(xml[span[0]:span[1]]):
            return span
    return None


def nadji_paragraf(xml: str, uvjet):
    """Raspon prvog paragrafa čiji tekst zadovoljava uvjet."""
    for span in spanovi(xml, "w:p"):
        if uvjet(tekst(xml[span[0]:span[1]])):
            return span
    return None
