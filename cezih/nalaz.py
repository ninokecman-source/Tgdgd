"""
e-Nalaz: sastavljanje i slanje nalaza (FHIR DiagnosticReport) te dohvat
nalaza pacijenta.

PROVJERI S CEZIH DOKUMENTACIJOM prije produkcije: konstante ispod i profil
(`PROFIL_NALAZ`) razumni su zadani odabiri, ne službena specifikacija.
"""

import base64
import uuid
from datetime import datetime, timezone

from . import oib as oib_mod
from .client import CezihGreska, CezihKlijent

SUSTAV_OIB = "http://fhir.cezih.hr/specifikacije/identifikatori/OIB"
SUSTAV_USTANOVA = "http://fhir.cezih.hr/specifikacije/identifikatori/sifra-ustanove"
SUSTAV_NALAZ_ID = "urn:ietf:rfc:3986"
PROFIL_NALAZ = "http://fhir.cezih.hr/specifikacije/StructureDefinition/hr-diagnostic-report"


def sastavi_nalaz(cfg, pacijent_oib: str, naslov: str, tekst: str,
                  kategorija_kod: str = "LAB", pdf: bytes = None,
                  nalaz_id: str = None, vrijeme: datetime = None) -> dict:
    """Vrati FHIR transaction Bundle s DiagnosticReport-om za jednog pacijenta.

    nalaz_id se šalje kao identifikator u klinici: ponovno slanje istog nalaza
    s istim id-jem CEZIH može prepoznati kao dupli, umjesto da ga zapiše dvaput.
    """
    if not oib_mod.je_ispravan(pacijent_oib):
        raise ValueError(f"OIB pacijenta nije ispravan: {pacijent_oib!r}")
    if not tekst.strip():
        raise ValueError("Nalaz je prazan.")
    nalaz_id = nalaz_id or str(uuid.uuid4())
    vrijeme = (vrijeme or datetime.now(timezone.utc)).astimezone(timezone.utc)

    izvjesce = {
        "resourceType": "DiagnosticReport",
        "meta": {"profile": [PROFIL_NALAZ]},
        "identifier": [{"system": SUSTAV_NALAZ_ID, "value": f"urn:uuid:{nalaz_id}"}],
        "status": "final",
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": kategorija_kod}]}],
        "code": {"text": naslov},
        "subject": {"identifier": {"system": SUSTAV_OIB, "value": pacijent_oib}},
        "effectiveDateTime": vrijeme.isoformat(timespec="seconds"),
        "issued": vrijeme.isoformat(timespec="seconds"),
        "performer": [{"identifier": {"system": SUSTAV_USTANOVA, "value": cfg.organizacija_id}}],
        "conclusion": tekst,
    }
    if pdf:
        izvjesce["presentedForm"] = [{
            "contentType": "application/pdf",
            "data": base64.b64encode(pdf).decode("ascii"),
            "title": naslov,
        }]
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{
            "fullUrl": f"urn:uuid:{nalaz_id}",
            "resource": izvjesce,
            "request": {"method": "POST", "url": "DiagnosticReport"},
        }],
    }


def posalji_nalaz(klijent: CezihKlijent, **kw) -> dict:
    """Pošalji nalaz; vrati odgovor CEZIH-a. Baca CezihGreska ako nije prihvaćen."""
    odgovor = klijent.post("", sastavi_nalaz(klijent.cfg, **kw))
    for e in odgovor.get("entry", []):
        status = str((e.get("response") or {}).get("status", ""))
        if status and not status.startswith("2"):
            raise CezihGreska(f"CEZIH nije prihvatio nalaz: {status}", ishod=odgovor)
    return odgovor


def nalazi_pacijenta(klijent: CezihKlijent, pacijent_oib: str, od: str = None) -> list:
    """Dohvati nalaze pacijenta (po OIB-u); `od` je datum 'YYYY-MM-DD'."""
    if not oib_mod.je_ispravan(pacijent_oib):
        raise ValueError(f"OIB pacijenta nije ispravan: {pacijent_oib!r}")
    params = {"subject:identifier": f"{SUSTAV_OIB}|{pacijent_oib}"}
    if od:
        params["date"] = f"ge{od}"
    svezak = klijent.get("DiagnosticReport", params)
    return [e["resource"] for e in svezak.get("entry", []) if "resource" in e]
