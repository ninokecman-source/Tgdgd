"""Učitavanje cezih/config.json (nije u gitu - sadrži putove do certifikata)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PODRAZUMIJEVANA = Path(__file__).with_name("config.json")


class ConfigGreska(Exception):
    pass


@dataclass
class CezihConfig:
    base_url: str                      # korijen FHIR sučelja, bez završne kose crte
    client_cert: str                   # klinikin certifikat (PEM) za mTLS
    client_key: str                    # privatni ključ (PEM)
    ca_bundle: Optional[str] = None    # CA lanac CEZIH-a; None = sustavski
    token_url: Optional[str] = None    # ako je zadan, koristi se OAuth2 client_credentials
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scope: Optional[str] = None
    organizacija_id: str = ""          # identifikator klinike (HZZO šifra ustanove)
    timeout: int = 30
    retries: int = 3


def ucitaj(put=PODRAZUMIJEVANA) -> CezihConfig:
    put = Path(put)
    if not put.is_file():
        raise ConfigGreska(f"Nema {put}. Kopiraj cezih/config.example.json i popuni.")
    try:
        sirovo = json.loads(put.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigGreska(f"{put} nije ispravan JSON: {e}")
    obavezno = ["base_url", "client_cert", "client_key", "organizacija_id"]
    fale = [k for k in obavezno if not sirovo.get(k)]
    if fale:
        raise ConfigGreska(f"U {put} fale polja: {', '.join(fale)}")
    if sirovo.get("token_url") and not (sirovo.get("client_id") and sirovo.get("client_secret")):
        raise ConfigGreska("token_url traži i client_id i client_secret.")
    sirovo["base_url"] = sirovo["base_url"].rstrip("/")
    poznata = CezihConfig.__dataclass_fields__
    return CezihConfig(**{k: v for k, v in sirovo.items() if k in poznata})
