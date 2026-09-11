"""
Tekstovi svih automatskih poruka - u zasebnim dokumentima, ne u configu.

Isti princip koji već vrijedi za upute o lokaciji ('lokacija split.docx'):
svaka poruka koju skripte šalju ima svoj dokument u istom folderu u kojem
su Excel tablice (output_dir). Tekst se uređuje u Wordu, bez diranja
config.json i bez ijedne izmjene u kodu.

Očekivani nazivi dokumenata (velika/mala slova i kvačice nisu bitni,
nastavak smije biti .docx, .odt, .txt ili .md):

    lokacija split                 upute o dvorani i dolasku (po gradu)
    odgovor na prijavu             automatski odgovor na novu prijavu
    podsjetnik 10 dana             podsjetnik 10 dana prije tečaja
    podsjetnik 1 dan               podsjetnik dan prije tečaja
    potvrda uplate akontacija      uplaćena akontacija, ostatak preostaje
    potvrda uplate doplata         doplata kojom je kotizacija zatvorena
    potvrda uplate modul           cijeli modul uplaćen odjednom
    potvrda uplate program         cijeli program uplaćen odjednom
    izvjestaj centrali             mail uz tablicu koja ide centrali

NASLOV PORUKE: ako prvi redak dokumenta počinje s "Naslov:" (ili
"Subject:"), taj redak postaje naslov maila, a ostatak je tijelo poruke.
Ako ga nema, cijeli dokument je tijelo, a naslov ostaje onaj iz configa.

U tekst se uvrštavaju podaci u vitičastim zagradama - {first_name},
{course_code}, {location}, {dates}, {iznos} i slično; koji su dostupni,
piše u READMEu uz svaku poruku.

Ako dokument ne postoji, koristi se tekst iz config.json, a ako ni njega
nema, ugrađeni zadani tekst - tako ništa ne stane dok dokument ne napišeš.
"""

import re
import zipfile
from pathlib import Path

# Tekst se čita iz datoteke, pa su podržani samo formati iz kojih ga možemo
# izvući. .doc i .pdf nisu među njima - spremi takav dokument kao .docx.
NASTAVCI = [".docx", ".odt", ".txt", ".md"]

_OZNAKE_NASLOVA = ("naslov:", "subject:")

# Redak iz kojeg se čita naziv dvorane u dokumentu o lokaciji. Ako nijedan
# od ovih nije prisutan, uzima se prvi redak dokumenta.
_OZNAKE_DVORANE = ("dvorana:", "venue:", "lokacija:", "mjesto:", "adresa:")


def bez_dijakritika(tekst: str) -> str:
    zamjene = str.maketrans("čćžšđČĆŽŠĐ", "cczsdCCZSD")
    return str(tekst).translate(zamjene).lower().strip()


def nadji_dokument(mapa: Path, nazivi):
    """Nađi dokument po nazivu (bez nastavka). `nazivi` smije biti jedan
    naziv ili popis mogućih - vraća se prvi koji postoji. Velika/mala slova
    i kvačice se ne gledaju, pa 'Lokacija Split' i 'lokacija split' rade
    jednako."""
    if isinstance(nazivi, (str, Path)):
        nazivi = [nazivi]
    if not mapa or not Path(mapa).is_dir():
        return None

    datoteke = [p for p in sorted(Path(mapa).iterdir())
                if p.suffix.lower() in NASTAVCI and not p.name.startswith("~$")]
    for naziv in nazivi:
        if not naziv:
            continue
        trazeno = bez_dijakritika(naziv)
        for put in datoteke:
            if bez_dijakritika(put.stem) == trazeno:
                return put
    return None


def procitaj_tekst(put: Path) -> str:
    """Izvuče čisti tekst iz dokumenta. .docx i .odt su zip s XML-om, pa ne
    treba vanjska biblioteka; .txt i .md se čitaju kakvi jesu. Vrati prazan
    string ako se ne može pročitati - tada poruka koja taj tekst treba neće
    biti poslana."""
    put = Path(put)
    nastavak = put.suffix.lower()

    if nastavak in (".txt", ".md"):
        try:
            tekst = put.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            try:
                tekst = put.read_text(encoding="cp1250")
            except (OSError, UnicodeDecodeError):
                return ""
        return "\n".join(r.rstrip() for r in tekst.splitlines()).strip("\n")

    unutra = {".docx": "word/document.xml", ".odt": "content.xml"}.get(nastavak)
    if not unutra:
        return ""
    try:
        with zipfile.ZipFile(put) as z:
            xml = z.read(unutra).decode("utf-8", errors="replace")
    except Exception:
        return ""

    xml = re.sub(r"</(w:p|text:p|text:h)>", "\n", xml)
    xml = re.sub(r"<(w:br|text:line-break)[^>]*/>", "\n", xml)
    tekst = re.sub(r"<[^>]+>", "", xml)
    tekst = (tekst.replace("&amp;", "&").replace("&lt;", "<")
                  .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
    # Word zna ubaciti nedjeljivi razmak; u mailu je običan razmak čitljiviji.
    tekst = tekst.replace("\xa0", " ")
    return "\n".join(r.rstrip() for r in tekst.splitlines()).strip("\n")


def rastavi_naslov(tekst: str):
    """Ako prvi neprazan redak počinje s 'Naslov:', vrati (naslov, ostatak).
    Inače (None, cijeli tekst)."""
    redci = tekst.splitlines()
    for i, redak in enumerate(redci):
        if not redak.strip():
            continue
        prvi = redak.strip()
        for oznaka in _OZNAKE_NASLOVA:
            if prvi.lower().startswith(oznaka):
                naslov = prvi[len(oznaka):].strip()
                ostatak = "\n".join(redci[i + 1:]).strip("\n")
                return (naslov or None), ostatak
        break
    return None, tekst


def ucitaj_predlozak(mapa: Path, nazivi):
    """Vrati {'naslov', 'tijelo', 'datoteka'} iz dokumenta, ili None ako
    dokument ne postoji odnosno iz njega se ne može pročitati tekst."""
    put = nadji_dokument(mapa, nazivi)
    if put is None:
        return None
    tekst = procitaj_tekst(put)
    if not tekst.strip():
        return None
    naslov, tijelo = rastavi_naslov(tekst)
    return {"naslov": naslov, "tijelo": tijelo, "datoteka": put}


def dohvati(mapa, nazivi, config=None, kljuc_naslov=None, kljuc_tijela=None,
            zadani_naslov=None, zadano_tijelo=None):
    """Nađi tekst poruke po redoslijedu: dokument u mapi -> config.json ->
    ugrađeni zadani tekst.

    Vraća (naslov, tijelo, izvor), gdje je `izvor` naziv datoteke odnosno
    'config.json' / 'ugrađeni tekst' - da se u pregledu vidi odakle tekst
    dolazi. Tijelo je None ako nijedan izvor nema teksta."""
    config = config or {}

    naslov_cfg = config.get(kljuc_naslov) if kljuc_naslov else None
    naslov = naslov_cfg or zadani_naslov

    predlozak = ucitaj_predlozak(mapa, nazivi)
    if predlozak:
        return (predlozak["naslov"] or naslov,
                predlozak["tijelo"],
                predlozak["datoteka"].name)

    tijelo_cfg = config.get(kljuc_tijela) if kljuc_tijela else None
    if tijelo_cfg:
        return naslov, tijelo_cfg, "config.json"

    if zadano_tijelo:
        return naslov, zadano_tijelo, "ugrađeni tekst"

    return naslov, None, "nema teksta"


def naziv_lokacije(location: str) -> str:
    """'Split' -> 'lokacija split' (naziv dokumenta s uputama)."""
    return f"lokacija {bez_dijakritika(location)}" if location else ""


def dokument_lokacije(mapa: Path, location: str):
    return nadji_dokument(mapa, naziv_lokacije(location)) if location else None


def rastavi_lokaciju(tekst: str):
    """Rastavi dokument o lokaciji na (dvorana, upute).

    Redak označen s 'Dvorana:' (ili Venue/Adresa/...) je podatak, ne
    rečenica: postaje {venue} i miče se iz {lokacija_tekst}, pa se naziv
    dvorane u poruci ne ponovi dvaput. Ako takvog retka nema, dvorana je
    prvi redak dokumenta, a upute ostaju cijeli tekst kakav jest."""
    if not tekst:
        return "", ""

    redci = tekst.splitlines()
    for i, redak in enumerate(redci):
        golo = redak.strip()
        if not golo:
            continue
        for oznaka in _OZNAKE_DVORANE:
            if golo.lower().startswith(oznaka):
                vrijednost = golo[len(oznaka):].strip()
                if vrijednost:
                    upute = "\n".join(redci[:i] + redci[i + 1:]).strip("\n")
                    return vrijednost, upute

    prvi = next((r.strip() for r in redci if r.strip()), "")
    return prvi, tekst


def dvorana_iz_teksta(tekst: str) -> str:
    """Samo naziv dvorane - vidi rastavi_lokaciju()."""
    return rastavi_lokaciju(tekst)[0]


# --- pisanje dokumenta -------------------------------------------------------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _escape(tekst: str) -> str:
    return (tekst.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def napisi_docx(put: Path, tekst: str) -> None:
    """Snimi običan tekst kao .docx koji se otvara u Wordu. Bez vanjske
    biblioteke: .docx je zip s XML-om, a ovdje nam trebaju samo odlomci."""
    odlomci = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{_escape(r)}</w:t></w:r></w:p>"
        for r in tekst.splitlines() or [""]
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{odlomci}</w:body></w:document>"
    )
    put = Path(put)
    put.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(put, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
