# Zoho prijave -> Excel

Skripta čita mailove prijava (od `prijava@emmett-hr.com`) s tvog Zoho Mail
računa i podatke polaznika upisuje u Excel tablicu, po uzoru na Emmett
Technique Instructor Administration Sheet.

Za svaku kombinaciju **kod tečaja + grad** postoji zasebna `.xlsx` datoteka
(npr. `Modul 1&2 Split.xlsx`, `Modul 1&2 Zagreb.xlsx`, `Modul 1&2
Makarska.xlsx`...). Grad se automatski prepoznaje iz retka s tečajem —
nije ograničen na unaprijed zadani popis, radi za bilo koji grad. Prijava
se upisuje samo ako je u tom retku navedeno tvoje ime kao instruktora
(`instructor_name`) i kod tečaja je jedan od poznatih kodova — tako tuđe
prijave koje stignu na isti sandučić ne završe u tvojim tablicama. Provjeru
imena možeš isključiti s `"require_instructor_name": false`, ali onda se
upisuje svaka prijava s poznatim kodom tečaja.

Nove datoteke se kreiraju iz `template_admin_sheet.xlsx` (kopija tvog
stvarnog Emmett predloška — isti fontovi, boje, obrubi, visine redova),
tako da svaka izgleda identično originalu, samo popunjena podacima.

Za svakog polaznika upisuje se: ime, prezime, ulica, grad, poštanski broj,
email, mobitel (kolone iz predloška — Country se automatski postavlja na
"Croatia", "New/Revised" na "N"). **Financijski dio**
(Payment Received, VAT %) ostaju prazni/nepromijenjeni — te popunjavaš
ručno. Formule za zbrajanje (Total Income, provizije) su već u tablici i
Excel ih sam preračunava kad otvoriš datoteku.

Ako neka prijava premaši 19 predviđenih redova u tablici, skripta sama
umetne dodatni red i ispravno pomakne formule ispod.

## Tekstovi poruka u Word dokumentima (`predlosci.py`)

Tekst **svake** poruke koju sustav šalje stoji u svom Word dokumentu, u
istom folderu u kojem su Excel tablice (`output_dir`) — isto pravilo koje
već vrijedi za upute o lokaciji. Uređuješ ih u Wordu; config.json i kod se
ne diraju.

| Dokument | Poruka |
|---|---|
| `odgovor na prijavu.docx` | automatski odgovor na novu prijavu |
| `odgovor uvjeti akontacija.docx` | uvjeti plaćanja za tečaj s akontacijom |
| `odgovor uvjeti puni iznos.docx` | uvjeti plaćanja za ostale tečajeve |
| `podsjetnik 10 dana.docx` | podsjetnik 10 dana prije tečaja |
| `podsjetnik 1 dan.docx` | podsjetnik dan prije tečaja |
| `blok uplate akontacija.docx` | odlomak o ostatku kotizacije |
| `blok uplate puni iznos.docx` | odlomak o uplati punog iznosa |
| `potvrda uplate akontacija.docx` | uplaćena akontacija, ostatak preostaje |
| `potvrda uplate doplata.docx` | doplata kojom je kotizacija zatvorena |
| `potvrda uplate modul.docx` | cijeli modul (400 €) uplaćen odjednom |
| `potvrda uplate program.docx` | cijeli program (2400 €) uplaćen odjednom |
| `izvjestaj centrali.docx` | mail uz tablicu koja ide centrali |
| `lokacija <grad>.docx` | dvorana i upute za dolazak, po gradu |

Velika i mala slova te kvačice u nazivu nisu bitni. Podržani su `.docx`,
`.odt`, `.txt` i `.md`; `.pdf` i stari `.doc` ne mogu se pročitati.

**Naslov maila:** ako prvi redak dokumenta glasi `Naslov: …` (prolazi i
`Subject:`), taj redak postaje naslov poruke, a ostatak je tijelo.

**Podaci u vitičastim zagradama** (`{first_name}`, `{course_code}`,
`{iznos}` …) popunjavaju se sami — koji su gdje dostupni, piše uz svaku
poruku niže.

### Napravi ih jednom naredbom

```bash
python3 napravi_predloske.py --pregled    # pokaži što bi napravio
python3 napravi_predloske.py              # napravi ono što fali
```

Dokumenti se izrađuju od tekstova koji su dosad stajali u `config.json`,
pa ti ništa ne treba prepisivati. **Postojeći dokument se nikad ne mijenja
ni ne briše.** Jedini koji moraš napisati sam je `lokacija <grad>.docx`.

Ako dokumenta nema, tekst se i dalje uzima iz `config.json`, a ako ni tamo
nije upisan, koristi se ugrađeni zadani tekst — tako ništa ne stane dok
dokument ne napišeš. U logu uvijek piše odakle je tekst uzet.

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

Ako `--pregled` ništa ne pokaže, a nije jasno zašto, ispiši stanje svih
tablica — datum, broj polaznika, dvoranu i status svakog podsjetnika:

```bash
python send_reminders.py --popis
```

Uključuje se u `config.json` s `"send_reminders": true`, a rokovi i tekst
se podešavaju u polju `reminders`:

```json
"reminders": [
  {"days_before": 10, "subject": "...", "body": "..."},
  {"days_before": 1,  "subject": "...", "body": "..."}
]
```

Uz placeholdere iz automatske potvrde, ovdje su dostupni i:

| Placeholder | Odakle |
|---|---|
| `{venue}` | naziv dvorane iz dokumenta o lokaciji (redak `Dvorana: …`) |
| `{days_until}` | stvaran broj dana do tečaja |
| `{prvi_dan}` | prvi dan riječima — „3. listopada" |
| `{rok_uplate}` | tjedan dana prije početka (`payment_due_days_before`) |
| `{cijena}`, `{akontacija}`, `{preostali_iznos}` | iz `price_total` i `deposit_amount` |
| `{blok_uplate}` | dio o uplati, ovisno o tome ima li tečaj akontaciju |
| `{lokacija_tekst}` | tekst iz dokumenta s uputama za lokaciju |

### Upute za lokaciju u zasebnom dokumentu

Detaljne upute (adresa, put do lokacije, parking, poveznica na kartu) drže
se u Word dokumentu uz tablice, imenovanom po gradu: **`lokacija
Split.docx`**, `lokacija Zagreb.docx` i tako dalje. Velika i mala slova te
kvačice nisu bitni.

Tekst iz tog dokumenta se **ugrađuje u samu poruku** na mjesto
`{lokacija_tekst}` — dokument se ne šalje u privitku, polaznik sve pročita
u mailu.

Ako **prvi redak** dokumenta glasi `Dvorana: …` (prolazi i `Venue:`,
`Adresa:`, `Lokacija:`, `Mjesto:`), taj se redak čita kao naziv dvorane i
dostupan je kao `{venue}`, a iz `{lokacija_tekst}` se izbacuje — pa se
adresa u poruci ne ponovi dvaput. Primjer:

```
Dvorana: Sportski centar Gripe, dvorana 2, Osmih mediteranskih igara 2, Split
Ulaz je sa zapadne strane, pored kavane.
Parking ispred dvorane je besplatan vikendom.
```

Dvorana se **ne čita iz tablice** (polje M5) — stoji samo ovdje, uz ostale
upute, pa se mijenja na jednom mjestu.

Podržani su `.docx` i `.odt`, jer se iz njih može izvući tekst. `.pdf` i
stari `.doc` ne mogu se pročitati — spremi takav dokument kao `.docx`.

Ako dokumenta nema ili se iz njega ne može pročitati tekst, poruka se **ne
šalje** — skripta javi što nedostaje, pa to središ i podsjetnik ode sam.
Slike i formatiranje iz dokumenta se gube; u poruku ide čisti tekst.

Kako to radi u praksi:

- Svako pravilo pokriva prozor **do sljedećeg, užeg pravila**: uz 10 i 1
  dan, "10 dana prije" vrijedi za 10–2 dana, a "1 dan prije" samo za točno
  1 dan. Tako netko tko se prijavi 3 dana prije tečaja dobije informativnu
  poruku (s točnim brojem dana u naslovu), a ne obje odjednom.
- Poruka koja spominje `{venue}` ili `{lokacija_tekst}` **neće se poslati**
  ako dokumenta o lokaciji nema — skripta to javi u logu. Polje Venue (M5)
  u tablici se **ne koristi**; dvorana se upisuje samo u taj dokument.
- Tečajevi koji su danas ili su prošli se preskaču, kao i tablice s
  datumom koji se ne može pouzdano pročitati.
- U `sent_reminders.json` se pamti kome je koji podsjetnik poslan, pa se
  ponovnim pokretanjem nikome ne šalje isto dvaput.

Za automatsko pokretanje dodaj u cron još jednu liniju, uz onu za
`zoho_to_excel.py`:

```
0 8 * * * cd /putanja/do/ovog/foldera && /usr/bin/python3 send_reminders.py >> log.txt 2>&1
```

## Slanje tablice centrali nakon tečaja (`posalji_tablicu.py`)

Dan nakon što tečaj završi, popunjena Excel tablica se automatski šalje
Emmett centrali, s prigodnim tekstom na engleskom i tablicom u privitku.
Kopija ide i tebi, da imaš trag u Sentu.

```bash
python posalji_tablicu.py --pregled    # pokaži što bi poslao, bez slanja
```

Uključuje se s `"send_course_report": true`, a podešava ovako:

- `course_report_to` — primatelji
  (`["ozren.m@emmett-hr.com", "heidi@rossemmett.com.au"]`)
- `course_report_days_after` — koliko dana nakon **zadnjeg** dana tečaja
  (default `1`)
- `course_report_subject`, `course_report_body` — tekst; uz uobičajene
  placeholdere dostupan je i `{broj_polaznika}`

### Nepotpuna tablica se ne šalje

Prije slanja se provjerava je li tablica popunjena. Ako nešto nedostaje,
centrali **ne ide ništa** — umjesto toga tebi stigne mail s popisom što
fali. Provjerava se ono što skripte same ne upisuju, pa lako ostane prazno:

- Payment Received za svakog polaznika
- PDV % (nula je valjana vrijednost, prazno nije)
- zaglavlje tečaja: kod, mjesto, datumi, instruktor
- email adresa svakog polaznika

Kad to popuniš, tablica ode sama pri sljedećem prolasku. Obavijest o
nepotpunoj tablici ne dolazi svaki dan iznova — samo kad se popis
nedostataka promijeni (npr. upisao si PDV, a uplate još fale).

Kada se **ne** šalje: dok tečaj još traje, ako je tablica prazna (nema
nijednog polaznika), ako je nepotpuna, ako se datum ne može pročitati, i
ako je ta tablica već poslana — poslano se pamti u `sent_reports.json`.

Datum završetka se čita iz zapisa datuma u tablici, pa radi i za tečajeve
koji prelaze mjesec (`30.11.-01.12.2024.`) ili Novu godinu
(`31.12.-01.01.2027.`).

Za automatsko pokretanje, jednom dnevno:

```
30 9 * * * cd /putanja/do/ovog/foldera && /usr/bin/python3 posalji_tablicu.py >> log.txt 2>&1
```

**Napomena:** tablica sadrži osobne podatke polaznika (ime, adresa, email,
telefon). Šalje se centrali jer je to njihov administrativni obrazac.

## Provjera logova (`provjeri_logove.py`)

Skripte pišu u `log.txt` (prijave i podsjetnici) i `sync.log` (izvodi i
Solo). Ova skripta ih pregleda i **pošalje ti mail samo ako nađe problem** —
inače šuti, da ne puni sandučić.

```bash
python provjeri_logove.py           # tiho, javlja samo probleme
python provjeri_logove.py --test    # pošalje mail bez obzira na sve
python provjeri_logove.py --ispis   # ispiše nalaz u terminal
```

Javlja dvije stvari:

- **greške** — tracebackove (cijeli blok, sa samom greškom na kraju), retke
  s `[!]` ili `[GREŠKA]`, izvode koji se ne poklapaju sa saldom, neuspjela
  slanja. Isti ponovljeni problem se sažima u jedan redak s brojem
  ponavljanja.
- **tišinu** — ako u nekom logu od zadnje provjere nema **nijednog** novog
  retka, znači da se ta skripta uopće nije pokrenula (ugašen cron, ugašeno
  računalo). Bez toga bi kvar prošao nezapaženo, jer greške nema ako se
  ništa ne izvršava.

Pamti dokle je pročitala svaki log (`log_check_state.json`), pa svaki put
javlja samo novo. Prvi put samo zapamti položaj i ne šalje ništa.

Praćeni logovi se po potrebi mijenjaju u `config.json`:

```json
"watch_logs": {
  "prijave i podsjetnici": "/Users/ime/Tgdgd/log.txt",
  "izvodi i Solo": "/Users/ime/Tgdgd-bank-solo/bank_solo/sync.log"
}
```

Za automatsko pokretanje svaka 3 dana u 9 ujutro:

```
0 9 */3 * * cd /putanja/do/ovog/foldera && /usr/bin/python3 provjeri_logove.py >> log.txt 2>&1
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
