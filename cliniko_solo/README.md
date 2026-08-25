# Cliniko + Solo integracija

Puni data model i pravila mapiranja: [`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md).

Arhitektura: **Cliniko API + Solo API → ovaj kod (data engine) → lokalna
baza → KPI engine → izvještaj**. Claude (ili bilo koji dashboard) dobiva
samo gotove KPI brojke iz `report.py`, nikad sirove retke termina/računa.

## Instalacija

```bash
pip install -r requirements.txt
cp cliniko_solo/config.example.json cliniko_solo/config.json
```

Popuni u `cliniko_solo/config.json`:

- `cliniko_api_key` — Cliniko → Postavke → API keys
- `cliniko_shard` — dio iz URL-a kad si prijavljen u Cliniko (npr. `au4`,
  `uk2`, `ca1`...) — vidi se u adresnoj traci web sučelja
- `cliniko_user_agent` — bilo koji identifikacijski string s tvojim
  emailom (Cliniko to traži, inače u nekom trenutku blokira zahtjeve)
- `solo_api_token` — Solo → Postavke servisa → API token
- `db_url` — po defaultu lokalni SQLite fajl; za Postgres promijeni u
  `postgresql://user:pass@host/dbname` (treba i `psycopg2-binary` u
  requirements.txt)
- `matching` — tolerancije za povezivanje termina i računa (§3 u
  DATA_MODEL.md)

`cliniko_solo/config.json` sadrži tajne ključeve i nikad se ne smije
commitati (već je u `.gitignore`).

## Pokretanje

```bash
# 1. Dohvati podatke iz Clinika i Sola u lokalnu bazu, poveži termine s računima
python -m cliniko_solo.sync --since 2026-07-01 --until 2026-08-31

# 2. Ispiši KPI-jeve za period (klinika + svaki terapeut)
python -m cliniko_solo.report --from 2026-08-01 --to 2026-08-31

# ili kao JSON, za dalju obradu / dashboard
python -m cliniko_solo.report --from 2026-08-01 --to 2026-08-31 --json
```

## Poznata ograničenja (namjerno, ne skrivena)

- **Dostupnost terapeuta** trenutno se računa samo iz redovite tjedne
  `daily_availabilities` sheme, bez oduzimanja jednokratnih blokiranja
  (godišnji, bolovanje — Cliniko `Unavailable Block`). `available_hours`
  je zato gornja granica, ne točan broj. Dodavanje `/unavailable_blocks`
  je jasno označeno TODO u `kpi_engine.py`.
- **Matching termina i računa** je heuristički (datum + iznos + fuzzy ime),
  jer Solo račun nema polje koje izravno referencira Cliniko appointment
  ID. Vidi `docs/DATA_MODEL.md` §3 za točna pravila i preporuku (upisivanje
  Cliniko ID-a u `napomene` pri izdavanju računa) koja bi to učinila
  determinističkim.
- **JIR/ZKI polja** u `SoloInvoice` modelu su nullable i nepotvrđena — Solo
  dokumentacija ih ne navodi eksplicitno u `GET /racun` odgovoru; treba
  provjeriti na stvarnom računu.
- Ako klinika stvarno fakturira kroz Cliniko-ov vlastiti Invoice modul
  (koji ima izravan `appointment` link), taj put je pouzdaniji od
  cross-system matchinga sa Solom za taj dio prihoda — provjeri prije
  oslanjanja isključivo na `matching.py` (vidi DATA_MODEL.md §1.7).
