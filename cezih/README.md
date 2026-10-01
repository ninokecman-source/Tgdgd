# CEZIH - e-Nalaz / e-Karton

FHIR R4 klijent za slanje i dohvat nalaza (DiagnosticReport) prema CEZIH-u.

## Što radi
- mTLS s certifikatom klinike, opcionalno OAuth2 (`client_credentials`)
- provjera OIB-a prije slanja, slanje nalaza (tekst + opcionalni PDF), dohvat nalaza po OIB-u
- 4xx se ne ponavlja (da nalaz ne stigne dvaput), 5xx/429/mrežne greške se ponavljaju

## Što NIJE gotovo
Adrese, nazivi identifikatora i profil nalaza su pretpostavke - uskladi ih s
dokumentacijom koju dobiješ od CEZIH-a (konstante na vrhu `cezih/nalaz.py`).
Za produkciju su potrebni: ugovor/priključenje ustanove, certifikat, test
okruženje i obično certifikacija sučelja. Bez toga nema pristupa, ma kako kod radio.

## Pokretanje
    cp cezih/config.example.json cezih/config.json   # popuni
    python -m cezih provjeri
    python -m cezih posalji 69435151530 "Krvna slika" nalaz.txt [nalaz.pdf]
    python -m cezih nalazi 69435151530 2026-01-01
    python -m unittest tests.test_cezih
