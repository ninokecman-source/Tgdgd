# Zoho prijave -> Excel

Skripta čita mailove prijava (od `prijava@emmett-hr.com`) s tvog Zoho Mail
računa i podatke polaznika upisuje u Excel tablicu — svaka lokacija (Split,
Zagreb) u svoj sheet. Prijava se upisuje samo ako je u retku s
tečajem/mjestom/datumom navedeno tvoje ime kao instruktora.

Za svakog polaznika upisuje se: Ime i prezime, Ulica, Grad, Poštanski broj,
Telefon, Email, OIB.

## 1. Instalacija

Potreban je Python 3.9+.

```bash
pip install -r requirements.txt
```

## 2. Generiranje app-specific lozinke u Zohu

Zoho ne dopušta korištenje obične lozinke za IMAP pristup ako imaš
uključenu dvofaktorsku autentikaciju (a bez nje se i ne preporuča). Umjesto
toga generiraj posebnu lozinku samo za ovu skriptu:

1. Prijavi se na [Zoho Mail](https://mail.zoho.com) (ili zoho.eu ako ti je
   račun u EU data centru).
2. Idi na **Postavke (Settings) → Sigurnost (Security) → App Passwords**.
3. Klikni **Generate New Password**, daj joj naziv (npr. "Excel skripta") i
   kopiraj generiranu lozinku (prikazuje se samo jednom).

## 3. Postavljanje konfiguracije

Kopiraj `config.example.json` u `config.json` i popuni svoje podatke:

```bash
cp config.example.json config.json
```

Polja u `config.json`:

- `zoho_email` – tvoja Zoho mail adresa
- `zoho_app_password` – lozinka generirana u koraku 2
- `imap_host` – `imap.zoho.eu` za EU data centar, `imap.zoho.com` za US.
  Ako jedan ne radi, probaj drugi.
- `sender_filter` – adresa s koje stižu prijave (`prijava@emmett-hr.com`)
- `instructor_name` – tvoje ime točno onako kako se pojavljuje u mailu
  (npr. `Nino Kecman`)
- `locations` – popis lokacija/sheetova koje pratiš (npr. `["Split", "Zagreb"]`)
- `excel_path` – puna putanja do Excel datoteke (može biti i iCloud Drive
  folder, npr. `/Users/tvoje_ime/Library/Mobile Documents/com~apple~CloudDocs/Prijave/Prijave.xlsx`)
- `state_path` – datoteka u kojoj skripta pamti koje je mailove već obradila
  (da ne bi duplicirala unose); ne treba dirati

**Napomena:** `config.json` sadrži lozinku i nikad se ne smije commitati u
git (već je dodan u `.gitignore`).

## 4. Pokretanje

```bash
python zoho_to_excel.py
```

Skripta će:
- pronaći sve nove mailove od `sender_filter` adrese,
- za svaki provjeriti sadrži li tvoje ime i jednu od zadanih lokacija,
- ako da — dodati red u odgovarajući sheet u Excel tablici,
- zapamtiti koje mailove je već obradila (`processed_uids.json`), tako da
  ponovno pokretanje ne stvara duplikate.

## 5. Automatsko pokretanje (raspored)

Da se skripta sama pokreće periodički (npr. svaki dan), koristi scheduler
na svom računalu — ovo se ne može pokretati odavde jer skripta piše u
datoteku na tvom disku.

**macOS/Linux (cron)** – `crontab -e` pa dodaj (svaki dan u 8h ujutro):

```
0 8 * * * cd /putanja/do/ovog/foldera && /usr/bin/python3 zoho_to_excel.py >> log.txt 2>&1
```

**Windows (Task Scheduler)** – kreiraj novi zadatak koji pokreće:

```
python.exe C:\putanja\do\ovog\foldera\zoho_to_excel.py
```

s rasporedom po želji (npr. dnevno).

## Ako format maila varira

Skripta prepoznaje red s tečajem/mjestom/instruktorom tako da preskoči prvi
fiksni redak ("Prijava - kliknete željeni Tečaj...") i uzme sljedeći redak
koji sadrži uzorak s crticama/datumom. Ako Emmett HR promijeni predložak
maila, javi pa se prilagodi parsiranje.
