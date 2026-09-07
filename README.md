# Zoho prijave -> Excel

Skripta čita mailove prijava (od `prijava@emmett-hr.com`) s tvog Zoho Mail
računa i podatke polaznika upisuje u Excel tablicu, po uzoru na Emmett
Technique Instructor Administration Sheet.

Za svaku kombinaciju **kod tečaja + grad** postoji zasebna `.xlsx` datoteka
(npr. `Modul 1&2 Split.xlsx`, `Modul 1&2 Zagreb.xlsx`, `Modul 1&2
Makarska.xlsx`...). Grad se automatski prepoznaje iz retka s tečajem —
nije ograničen na unaprijed zadani popis, radi za bilo koji grad. Prijava
se upisuje samo ako je u tom retku navedeno tvoje ime kao instruktora i
kod tečaja je jedan od poznatih kodova.

Nove datoteke se kreiraju iz `template_admin_sheet.xlsx` (kopija tvog
stvarnog Emmett predloška — isti fontovi, boje, obrubi, visine redova),
tako da svaka izgleda identično originalu, samo popunjena podacima.

Za svakog polaznika upisuje se: ime, prezime, ulica, grad, poštanski broj,
email, mobitel (kolone iz predloška — Country se automatski postavlja na
"Croatia", "New/Revised" na "N"). Polje **Venue** i **financijski dio**
(Payment Received, VAT %) ostaju prazni/nepromijenjeni — te popunjavaš
ručno. Formule za zbrajanje (Total Income, provizije) su već u tablici i
Excel ih sam preračunava kad otvoriš datoteku.

Ako neka prijava premaši 19 predviđenih redova u tablici, skripta sama
umetne dodatni red i ispravno pomakne formule ispod.

## Automatska potvrda polazniku (opcionalno)

Skripta može, nakon što upiše prijavu u Excel, poslati i kratku potvrdnu
poruku direktno prijavljenom polazniku (na email koji je upisao u
prijavnicu) — koristi istu app-lozinku, preko SMTP-a, bez ikakve dodatne
registracije. Isključeno je po defaultu.

Da uključiš, u `config.json` postavi:
```json
"send_replies": true
```
i po želji prilagodi `reply_subject` i `reply_body`. Podržani placeholderi
popunjavaju se iz same prijave, za svakog polaznika zasebno:
`{first_name}`, `{last_name}`, `{course_code}`, `{location}`, `{dates}`,
`{instructor_name}`.

### Uvjeti plaćanja koji se razlikuju po tečaju

Cijena je ista za sve module, ali akontacija (i uvjeti otkazivanja vezani
uz nju) vrijedi samo za neke. Zato `reply_body` sadrži i placeholder
`{deposit_section}`, koji se popunjava ovisno o tečaju:

- `deposit_course_codes` — popis kodova tečaja koji imaju akontaciju
  (npr. `["Modul 1&2"]`)
- `reply_deposit_section` — tekst koji se šalje za te tečajeve (iznos
  akontacije, rok uplate, uvjeti otkazivanja)
- `reply_no_deposit_section` — tekst za sve ostale tečajeve (rok uplate
  punog iznosa, upućivanje na uvjete pohađanja)

Ako neki tečaj dobije/izgubi akontaciju, dovoljno je dodati ili maknuti
njegov kod iz `deposit_course_codes` — tekst se ne dira.

**Napomena:** poruka se šalje kao **nova** poruka polazniku (nije "reply"
na izvornu obavijest koju ti primiš, jer polaznik nije primatelj te
obavijesti — nema na što nastaviti nit razgovora).

## Automatski podsjetnici prije tečaja (`send_reminders.py`)

Zasebna skripta prolazi kroz sve tablice u `output_dir`, iz svake pročita
datum tečaja i sve upisane polaznike, pa im pošalje podsjetnik kad tečaj
dođe blizu — po defaultu **10 dana prije** (lokacija, što ponijeti,
podsjetnik na uplatu) i **1 dan prije** ("sutra počinje").

Prije nego pustiš da stvarno šalje, pogledaj što bi poslao:

```bash
python send_reminders.py --pregled
```

Uključuje se u `config.json` s `"send_reminders": true`, a rokovi i tekst
se podešavaju u polju `reminders`:

```json
"reminders": [
  {"days_before": 10, "subject": "...", "body": "..."},
  {"days_before": 1,  "subject": "...", "body": "..."}
]
```

Uz placeholdere iz automatske potvrde, ovdje su dostupni i `{venue}`
(dvorana — ono što ručno upišeš u polje Venue, ćelija M5) i `{days_until}`
(stvaran broj dana do tečaja).

Kako to radi u praksi:

- Svako pravilo pokriva prozor **do sljedećeg, užeg pravila**: uz 10 i 1
  dan, "10 dana prije" vrijedi za 10–2 dana, a "1 dan prije" samo za točno
  1 dan. Tako netko tko se prijavi 3 dana prije tečaja dobije informativnu
  poruku (s točnim brojem dana u naslovu), a ne obje odjednom.
- Poruka koja spominje `{venue}` **neće se poslati** ako je polje Venue u
  tablici prazno — skripta to javi u logu da znaš popuniti dvoranu.
- Tečajevi koji su danas ili su prošli se preskaču, kao i tablice s
  datumom koji se ne može pouzdano pročitati.
- U `sent_reminders.json` se pamti kome je koji podsjetnik poslan, pa se
  ponovnim pokretanjem nikome ne šalje isto dvaput.

Za automatsko pokretanje dodaj u cron još jednu liniju, uz onu za
`zoho_to_excel.py`:

```
0 8 * * * cd /putanja/do/ovog/foldera && /usr/bin/python3 send_reminders.py >> log.txt 2>&1
```

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
- `course_codes` – popis svih kodova tečaja koje prepoznaješ (Modul 1&2,
  Modul 3, Modul 4, Modul 5, Modul 6, Ponavljanje M6 i Praktičarski dan)
- `folder_roots` – Zoho folderi (uz INBOX koji se uvijek pretražuje) čiji
  se svi podfolderi pretražuju, npr. `["Split", "Zagreb"]` — ako imaš
  mailove ručno razvrstane u foldere po gradu/tečaju, dodaj ih ovdje
- `output_dir` – folder u koji se spremaju Excel datoteke (može biti i
  iCloud Drive folder, npr. `/Users/tvoje_ime/Library/Mobile Documents/com~apple~CloudDocs/Prijave`)
  — unutar njega se automatski stvara jedna `.xlsx` datoteka po kombinaciji
  kod tečaja + grad
- `state_path` – datoteka u kojoj skripta pamti koje je mailove već obradila
  (da ne bi duplicirala unose); ne treba dirati
- `since_date` – opcionalno, npr. `"2026-01-01"`; ako je postavljeno, u
  obzir se uzimaju samo mailovi primljeni od tog datuma nadalje (starije
  prijave se potpuno ignoriraju, ne dohvaćaju se s Zoho servera)
- `send_replies`, `smtp_host`, `smtp_port`, `reply_subject`, `reply_body` –
  postavke za automatsku potvrdu polazniku, vidi sekciju ispod

**Napomena:** `config.json` sadrži lozinku i nikad se ne smije commitati u
git (već je dodan u `.gitignore`).

## 4. Pokretanje

```bash
python zoho_to_excel.py
```

Skripta će:
- pretražiti INBOX i sve podfoldere unutar `folder_roots` (npr. Split,
  Zagreb i sve njihove podfoldere) za nove mailove od `sender_filter`
  adrese,
- za svaki provjeriti sadrži li poznati kod tečaja; grad se uzima iz
  naziva foldera (ako mail dolazi iz Split/Zagreb stabla) ili se izvlači
  iz teksta maila (za mailove u INBOX-u),
- ako da — dodati red u odgovarajuću `.xlsx` datoteku, imenovanu po kodu
  tečaja i gradu (kreirati je ako još ne postoji),
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
