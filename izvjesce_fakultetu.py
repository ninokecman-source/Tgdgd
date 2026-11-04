"""
Izvješće Fakultetu zdravstvenih znanosti, nakon modula u Splitu.

Obrazac je fakultetov i tekst mu ostaje nedirnut. Mijenja se samo ono što se
od modula do modula razlikuje: datum izrade, naziv i trajanje programa i broj
polaznika.

Financijska analiza se ne popunjava. Odjeljak ostaje prazan kakav u obrascu
i jest, pa ga po potrebi ispuniš rukom.

Predložak je prazan obrazac uz tablice ('izvjesce fakultetu.docx'), isti
princip kao 'lokacija Split.docx'. Gotovo izvješće nastaje u:

    <output_dir>/Izvjesca/<Mjesto> <Kod tečaja> <Godina>.pdf

Uz PDF ostaje i .docx iz kojeg je nastao - obrazac se puni kao Wordov
dokument jer je takav i dobiven, pa mu oblikovanje ostaje netaknuto, a PDF
je ono što se šalje. Za pretvaranje treba LibreOffice:

    sudo apt install -y libreoffice-writer

Potpis se dodaje ako uz tablice, u mapi 'Marka', stoji 'potpis.png' (ili
.jpg). Ako ga nema, izvješće nastane s praznom crtom za potpis.

Pokretanje:
    python3 izvjesce_fakultetu.py --tecaj "Modul 1&2 Split.xlsx"
    python3 izvjesce_fakultetu.py --tecaj Split --pregled
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

import docx_izmjena as dx
import predlosci
import tablice
from napravi_certifikate import ime_datoteke
from send_reminders import (
    FIRST_PARTICIPANT_ROW,
    MJESECI_GENITIV,
    course_info,
    find_totals_row,
    parse_course_dates,
)
from zoho_to_excel import load_config, with_retry

NAZIV_PREDLOSKA = "izvjesce fakultetu"
COL_FIRST_NAME, COL_LAST_NAME = 2, 3
COL_NOVI_ILI_PONOVNI = 11

# Natpisi koji su dio samog obrasca; sve ostalo u financijskoj tablici je
# stavka nekog tečaja i briše se.
KOSTUR_FINANCIJA = ("PLANIRANI", "PRIHODI", "RASHODI", "Ukupno", "Višak",
                    "Od strane organizatora")

BROJEVI_RIJECIMA = {1: "jedan", 2: "dva", 3: "tri", 4: "četiri", 5: "pet",
                    6: "šest", 7: "sedam", 8: "osam", 9: "devet", 10: "deset"}


def datum_izrade(danas: date) -> str:
    """'2. studenoga 2026' - zapis kakav već stoji na naslovnici obrasca."""
    return f"{danas.day}. {MJESECI_GENITIV[danas.month - 1]} {danas.year}"


def citaj_tablicu(xlsx_path: Path, config: dict) -> dict:
    wb = with_retry(lambda: load_workbook(xlsx_path, data_only=True),
                    retry_on=(PermissionError, OSError))
    if "podaci" not in wb.sheetnames:
        sys.exit(f"{xlsx_path.name} nema list 'podaci'.")
    ws = wb["podaci"]

    info = course_info(ws, config)
    ukupno, ponovnih = 0, 0
    for row in range(FIRST_PARTICIPANT_ROW, find_totals_row(ws)):
        ime = ws.cell(row=row, column=COL_FIRST_NAME).value
        prezime = ws.cell(row=row, column=COL_LAST_NAME).value
        if not ime and not prezime:
            continue
        ukupno += 1
        oznaka = str(ws.cell(row=row, column=COL_NOVI_ILI_PONOVNI).value or "").strip()
        # U tablici stoji "New (N) or Revised (R)" - ponavljači su R.
        if oznaka.upper().startswith("R"):
            ponovnih += 1

    info["polaznika"] = ukupno
    info["ponovnih"] = ponovnih
    return info


def recenica_o_polaznicima(info: dict) -> str:
    """'Tečaju je pristupilo ukupno 16 polaznika, od kojih su dva polaznika
    ponavljala modul 1&2.' - drugi dio otpada ako ponavljača nema."""
    broj = info["polaznika"]
    rijec = "polaznik" if broj == 1 else "polaznika"
    recenica = f"Tečaju je pristupilo ukupno {broj} {rijec}"
    ponovnih = info["ponovnih"]
    if ponovnih == 1:
        recenica += f", od kojih je jedan polaznik ponavljao {info['course_code']}"
    elif ponovnih > 1:
        koliko = BROJEVI_RIJECIMA.get(ponovnih, str(ponovnih))
        recenica += (f", od kojih su {koliko} polaznika ponavljala "
                     f"{info['course_code']}")
    return recenica + "."


def ispuni_dokument(xml: str, info: dict, config: dict, danas: date) -> tuple:
    """(ispunjeni XML, popis mjesta koja nisu nađena).

    Obrazac je fakultetov i može se promijeniti. Zato se svako mjesto traži
    po tekstu koji na njemu piše, a ono što se ne nađe se prijavi - bolje
    nego da izvješće tiho izađe s pola podataka."""
    izmjene, promaseno = [], []

    def paragraf(uvjet, novi, sto):
        span = dx.nadji_paragraf(xml, uvjet)
        if span is None:
            promaseno.append(sto)
            return False
        izmjene.append((*span, dx.postavi_tekst(xml[span[0]:span[1]], novi)))
        return True

    def red_tablice(span_tablice, naslov, vrijednost, novi_naslov=None):
        """Drugoj ćeliji reda čiji prvi stupac počinje zadanim tekstom upiši
        vrijednost. Red se traži po natpisu, a ne po rednom broju, da izmjena
        obrasca ne pomakne sve. `novi_naslov` prepisuje i sam natpis."""
        for red in dx.redovi_tablice(xml, span_tablice):
            celije = dx.celije_reda(xml, red)
            if len(celije) < 2:
                continue
            if dx.tekst(xml[celije[0][0]:celije[0][1]]).startswith(naslov):
                poc, kraj = celije[1]
                izmjene.append((poc, kraj, dx.postavi_celiju(xml[poc:kraj], vrijednost)))
                if novi_naslov:
                    poc, kraj = celije[0]
                    izmjene.append((poc, kraj,
                                    dx.postavi_celiju(xml[poc:kraj], novi_naslov)))
                return True
        promaseno.append(f"redak '{naslov}'")
        return False

    # --- naslovna: mjesto i datum izrade ('Split, 24. listopad 2026')
    paragraf(lambda t: t.startswith(f"{info['location']},"),
             f"{info['location']}, {datum_izrade(danas)}", "datum na naslovnici")

    # --- 1. opće informacije
    opce = dx.nadji_tablicu(xml, "Naziv programa")
    if opce is None:
        promaseno.append("tablica s općim informacijama")
    else:
        red_tablice(opce, "Naziv programa", f"Tečaj Emmett tehnike {info['course_code']}")
        red_tablice(opce, "Trajanje programa", info["dates"])
        red_tablice(opce, "Broj upisanih polaznika", str(info["polaznika"]))
        red_tablice(opce, "Broj polaznika koji su završili", str(info["polaznika"]))

    # --- 2.2 broj i profil polaznika
    paragraf(lambda t: t.startswith("Tečaju je pristupilo"),
             recenica_o_polaznicima(info), "rečenica o broju polaznika")

    # --- 3. financijska analiza: odjeljak ostaje, ali prazan
    #
    # U obrascu su zaostale stavke i iznosi iz tečaja po kojem je složen
    # ('Skripte 350 Eura', 'Emmett Australija', dvije nule). Kad bi ostali,
    # svako bi izvješće nosilo tuđe brojke. Zato se brišu svi iznosi i svaka
    # stavka, a ostaje samo kostur obrasca.
    financ = dx.nadji_tablicu(xml, "Ukupno rashodi")
    if financ is None:
        promaseno.append("financijska tablica")
    else:
        for red in dx.redovi_tablice(xml, financ):
            celije = dx.celije_reda(xml, red)
            if not celije:
                continue
            naslov = dx.tekst(xml[celije[0][0]:celije[0][1]])
            if not naslov.startswith(KOSTUR_FINANCIJA):
                izmjene.append((*celije[0], dx.postavi_celiju(
                    xml[celije[0][0]:celije[0][1]], "")))
            for poc, kraj in celije[1:]:
                if dx.tekst(xml[poc:kraj]):
                    izmjene.append((poc, kraj, dx.postavi_celiju(xml[poc:kraj], "")))

    # --- 4. mjere kvalitete: spomen modula u opisu prakse
    kvaliteta = dx.nadji_tablicu(xml, "Vrjednovanje prakse")
    if kvaliteta:
        for red in dx.redovi_tablice(xml, kvaliteta):
            for poc, kraj in dx.celije_reda(xml, red):
                stari = dx.tekst(xml[poc:kraj])
                if "modulima 1&2" in stari:
                    izmjene.append((poc, kraj, dx.postavi_celiju(
                        xml[poc:kraj],
                        stari.replace("modulima 1&2", info["course_code"]))))

    # --- potpis
    paragraf(lambda t: t.startswith("Titula, ime i prezime"),
             config.get("izvjesce_potpisnik",
                        f"{info['instructor_name']}, instruktor"),
             "ime ispod crte za potpis")

    return dx.primijeni(xml, izmjene), promaseno


def ubaci_potpis(xml: str, odnos_id: str, sirina_cm: float, visina_cm: float) -> str:
    """Sliku potpisa stavi u prazan paragraf iznad crte za potpis."""
    crta = dx.nadji_paragraf(xml, lambda t: t.startswith("______"))
    if crta is None:
        return xml
    prije = [s for s in dx.spanovi(xml, "w:p") if s[1] <= crta[0]]
    if not prije or dx.tekst(xml[prije[-1][0]:prije[-1][1]]):
        return xml      # iznad crte nema praznog paragrafa, ne diraj ništa

    poc, kraj = prije[-1]
    cx, cy = int(sirina_cm * 360000), int(visina_cm * 360000)
    crtez = (
        '<w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:docPr id="901" name="Potpis"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="901" name="Potpis"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill>'
        f'<a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="{odnos_id}"/>'
        '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline>'
        '</w:drawing></w:r>')
    paragraf = xml[poc:kraj]
    novi = paragraf[:-len("</w:p>")] + crtez + "</w:p>"
    return xml[:poc] + novi + xml[kraj:]


def nadji_potpis(mapa_marke: Path):
    for naziv in ("potpis.png", "potpis.jpg", "potpis.jpeg"):
        put = mapa_marke / naziv
        if put.is_file():
            return put
    return None


def mjere_slike(put: Path, visina_cm: float = 2.0) -> tuple:
    """(širina, visina) u centimetrima, uz zadanu visinu i očuvan omjer."""
    try:
        from PIL import Image
        with Image.open(put) as im:
            omjer = im.width / im.height
    except Exception:
        omjer = 3.0
    return round(visina_cm * omjer, 2), visina_cm


# LibreOffice pretvara .docx u PDF. Prvi koji postoji se koristi; put se po
# potrebi zadaje s "soffice_path" u config.json.
PUTEVI_SOFFICEA = [
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/snap/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


def nadji_soffice(config: dict):
    zadano = config.get("soffice_path")
    if zadano:
        return zadano if Path(zadano).exists() else None
    for put in PUTEVI_SOFFICEA:
        if Path(put).exists():
            return put
    return shutil.which("soffice") or shutil.which("libreoffice")


def u_pdf(docx_put: Path, config: dict) -> Path:
    """Isti dokument kao PDF, uz .docx. Vraća put do PDF-a.

    Obrazac se puni kao .docx jer je takav i dobiven od fakulteta i tako mu
    oblikovanje ostaje netaknuto; PDF je ono što se šalje. Pretvara
    LibreOffice, jer jedini čita .docx onako kako ga čita i Word.

    Vlastiti profil u privremenoj mapi: bez njega se dva pokretanja odjednom
    potuku oko istog profila u domu."""
    soffice = nadji_soffice(config)
    if soffice is None:
        raise RuntimeError(
            "ne nalazim LibreOffice, pa PDF ne mogu napraviti. Instaliraj ga "
            "('sudo apt install -y libreoffice-writer') ili upiši put u "
            'config.json kao "soffice_path"')

    with tempfile.TemporaryDirectory() as privremeno:
        rezultat = subprocess.run(
            [soffice, "--headless", "--norestore",
             f"-env:UserInstallation=file://{privremeno}/profil",
             "--convert-to", "pdf", "--outdir", str(docx_put.parent),
             str(docx_put)],
            capture_output=True, text=True, timeout=300)

    pdf_put = docx_put.with_suffix(".pdf")
    if not pdf_put.exists() or pdf_put.stat().st_size == 0:
        poruka = (rezultat.stderr or rezultat.stdout or "").strip().splitlines()
        kraj = poruka[-1] if poruka else f"LibreOffice je vratio {rezultat.returncode}"
        raise RuntimeError(f"PDF nije napravljen: {kraj}")
    return pdf_put


def napravi(predlozak: Path, cilj: Path, info: dict, config: dict,
            danas: date, potpis: Path) -> list:
    with zipfile.ZipFile(predlozak) as zip_ulaz:
        dijelovi = {ime: zip_ulaz.read(ime) for ime in zip_ulaz.namelist()}

    xml = dijelovi["word/document.xml"].decode("utf-8")
    xml, promaseno = ispuni_dokument(xml, info, config, danas)

    if potpis is not None:
        nastavak = potpis.suffix.lower().lstrip(".")
        nastavak = "jpeg" if nastavak == "jpg" else nastavak
        odnos_id = "rIdPotpis"
        dijelovi[f"word/media/potpis.{nastavak}"] = potpis.read_bytes()

        odnosi = dijelovi["word/_rels/document.xml.rels"].decode("utf-8")
        odnosi = odnosi.replace(
            "</Relationships>",
            f'<Relationship Id="{odnos_id}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/image" '
            f'Target="media/potpis.{nastavak}"/></Relationships>')
        dijelovi["word/_rels/document.xml.rels"] = odnosi.encode("utf-8")

        vrste = dijelovi["[Content_Types].xml"].decode("utf-8")
        if f'Extension="{nastavak}"' not in vrste:
            vrste = vrste.replace(
                "</Types>",
                f'<Default Extension="{nastavak}" ContentType="image/{nastavak}"/>'
                "</Types>")
            dijelovi["[Content_Types].xml"] = vrste.encode("utf-8")

        sirina, visina = mjere_slike(potpis)
        xml = ubaci_potpis(xml, odnos_id, sirina, visina)

    dijelovi["word/document.xml"] = xml.encode("utf-8")

    cilj.parent.mkdir(parents=True, exist_ok=True)
    privremeno = cilj.with_suffix(".tmp.docx")
    with zipfile.ZipFile(privremeno, "w", zipfile.ZIP_DEFLATED) as zip_izlaz:
        for ime, sadrzaj in dijelovi.items():
            zip_izlaz.writestr(ime, sadrzaj)
    privremeno.replace(cilj)
    return promaseno


def main():
    parser = argparse.ArgumentParser(
        description="Izvješće fakultetu nakon modula u Splitu.")
    parser.add_argument("--tecaj", required=True, metavar="DIO NAZIVA")
    parser.add_argument("--pregled", action="store_true",
                        help="Samo ispiši što bi ušlo, bez pravljenja dokumenta")
    args = parser.parse_args()

    config = load_config()
    output_dir = Path(config["output_dir"])
    if not output_dir.exists():
        sys.exit(f"Ne postoji folder s tablicama: {output_dir}")

    trazeno = predlosci.bez_dijakritika(args.tecaj)
    datoteke = [p for p in tablice.nadji(output_dir)
                if trazeno in predlosci.bez_dijakritika(p.name)]
    if not datoteke:
        sys.exit(f"Nijedna tablica u nazivu nema {args.tecaj!r}.")
    if len(datoteke) > 1:
        sys.exit("Na ovo ime pristaje više tablica: "
                 + ", ".join(p.name for p in datoteke))
    xlsx_path = datoteke[0]

    info = citaj_tablicu(xlsx_path, config)
    danas = date.today()

    print(f"{info['course_code']} / {info['location']} ({info['dates']})")
    print(f"  polaznika: {info['polaznika']}"
          + (f", od toga ponavljača: {info['ponovnih']}" if info["ponovnih"] else ""))
    if args.pregled:
        print("\nPregled - dokument nije napravljen.")
        return

    predlozak = predlosci.nadji_dokument(output_dir, NAZIV_PREDLOSKA)
    if predlozak is None:
        sys.exit(f"Nedostaje predložak '{NAZIV_PREDLOSKA}.docx' u {output_dir}.")

    potpis = nadji_potpis(output_dir / "Marka")
    if potpis is None:
        print("  [!] Nema 'potpis.png' u mapi Marka - izvješće ide s praznom "
              "crtom za potpis.")

    _, kraj = parse_course_dates(info["dates"])
    godina = kraj.year if kraj else danas.year
    naziv = ime_datoteke(f"{info['location']} {info['course_code']} {godina}")
    cilj = output_dir / "Izvjesca" / f"{naziv}.docx"

    promaseno = napravi(predlozak, cilj, info, config, danas, potpis)
    for sto in promaseno:
        print(f"  [!] U obrascu ne nalazim {sto} - to mjesto ostaje kakvo je bilo.")

    try:
        pdf_put = u_pdf(cilj, config)
    except Exception as e:
        print(f"  [!] {e}")
        print(f"\nNapravljen je samo Word dokument: {cilj}")
        return
    print(f"\nGotovo. {pdf_put}")
    print(f"  (uz njega stoji i {cilj.name}, ako nešto treba dotjerati)")


if __name__ == "__main__":
    main()
