# Data model: Cliniko + Solo integracija

Ova specifikacija opisuje točno koja polja povlačimo iz Cliniko i Solo API-ja,
kako ih spremamo u internu bazu i po kojim pravilima povezujemo Cliniko
termine sa Solo računima. Polja su provjerena izravno u službenoj
dokumentaciji (docs.api.cliniko.com i solo.com.hr/api-dokumentacija), ne
nagađana.

## 1. Cliniko — entiteti i polja

Baza: `https://api.{shard}.cliniko.com/v1/` (shard npr. `au4`, `uk2` — vidi se
u URL-u kad si prijavljen u Cliniko web sučelju). Auth: HTTP Basic, korisničko
ime = API ključ, lozinka prazna. Obavezan `User-Agent` header (ime aplikacije
+ email), inače Cliniko nakon nekog vremena blokira zahtjeve. Rate limit: 200
zahtjeva/min po korisniku (429 + `X-RateLimit-Reset` ako se premaši).
Paginacija: `page`, `per_page` (max 100), odgovor sadrži `total_entries` i
`links.next`. Filtriranje: `q[]=polje:operator vrijednost`, npr.
`q[]=starts_at:>=2026-08-01T00:00:00Z`.

### 1.1 Business (poslovnica)
`GET /businesses`, `/businesses/{id}`

Polja koja povlačimo: `id`, `business_name`, `display_name`, `address_1`,
`address_2`, `city`, `state`, `post_code`, `country`, `country_code`,
`time_zone_identifier`, `appointment_type_ids`, `archived_at`, `created_at`,
`updated_at`.

### 1.2 Practitioner (terapeut)
`GET /practitioners`, `/practitioners/{id}`

Polja: `id`, `first_name`, `last_name`, `display_name`, `title`,
`designation`, `label`, `active`, `show_in_online_bookings`,
`default_appointment_type`, `created_at`, `updated_at`.

### 1.3 AppointmentType (vrsta tretmana)
`GET /appointment_types`

Polja: `id`, `name`, `category`, `color`, `duration_in_minutes`,
`deposit_price`, `max_attendees`, `archived_at`, `created_at`, `updated_at`.

`duration_in_minutes` je osnova za izračun "booked_hours"; `deposit_price`
koristimo kao okvirnu referentnu cijenu usluge kod matchinga s Solo računima
(vidi §3) dok ne postoji točnija cjenovna tablica.

### 1.4 Patient (pacijent)
`GET /patients`

Od cijele (vrlo opsežne, medicinske) sheme povlačimo samo financijski/
identifikacijski podskup: `id`, `first_name`, `last_name`, `label`, `email`,
`invoice_default_to`, `invoice_email`, `archived_at`, `created_at`,
`updated_at`. Medicinska polja (medical_alerts, medicare, gender_identity...)
namjerno ne povlačimo — nisu nam potrebna za financijsku/operativnu analitiku
i nema smisla nepotrebno držati osjetljive zdravstvene podatke u vlastitoj bazi.

### 1.5 IndividualAppointment (termin) — najvažniji entitet
`GET /individual_appointments` (ili `/appointments`, filtrirano po
`business_id`, `practitioner_id`, `starts_at` rasponu itd.)

Polja koja povlačimo: `id`, `starts_at`, `ends_at`, `business`,
`practitioner`, `patient`, `appointment_type`, `patient_arrived`,
`did_not_arrive`, `cancelled_at`, `cancellation_reason`,
`cancellation_reason_description`, `cancellation_note`, `invoice_status`,
`archived_at`, `deleted_at`, `created_at`, `updated_at`.

**Izvedeno stanje termina** (`appointment_state`), po prioritetu:

| Uvjet | Stanje |
|---|---|
| `deleted_at IS NOT NULL` | ignoriraj (obrisan termin, ne ulazi u analitiku) |
| `cancelled_at IS NOT NULL` | `CANCELLED` (razlog: `cancellation_reason_description`) |
| `did_not_arrive = true` | `NO_SHOW` |
| `patient_arrived = true` | `COMPLETED` |
| termin u budućnosti | `BOOKED` |
| termin u prošlosti, ništa od gore označeno | `UNKNOWN` (treba ručnu doradu u Cliniku) |

### 1.6 DailyAvailability (redovita dostupnost terapeuta)
`GET /daily_availabilities`, `/practitioners/{id}/daily_availabilities`,
`/businesses/{id}/daily_availabilities`

Polja: `id`, `business`, `practitioner`, `day_of_week` (0 = ponedjeljak … 6 =
nedjelja), `time_zone_identifier`, `availabilities[]` (svaki element ima
`starts_at`/`ends_at` kao `"HH:MM"`, ne datum-vrijeme).

Tjedni dostupni kapacitet terapeuta u poslovnici = zbroj trajanja svih
`availabilities` blokova po danu u tjednu. Za točan mjesečni izračun treba
dodatno oduzeti jednokratna blokiranja (godišnji odmor, bolovanje) — Cliniko
ih vodi kao **Unavailable Block** (`GET /unavailable_blocks`), koji u ovoj
prvoj verziji sustava još ne povlačimo; dodano kao poznato proširenje u
`kpi_engine.py` (`TODO` komentar), ne kao skriveni izvor greške.

### 1.7 Invoice / InvoiceItem (Cliniko interno fakturiranje)
`GET /invoices`, `/invoice_items` (i filtrirano po `appointment_id`,
`patient_id`, `practitioner_id`)

Invoice polja: `id`, `number`, `issue_date`, `status` (10=Open, 20=Paid,
30=Closed, 40=Open credit), `status_description`, `net_amount`, `tax_amount`,
`total_amount`, `discounted_amount`, `patient`, `practitioner`, `business`,
**`appointment`** (izravna veza!), `closed_at`, `archived_at`.

InvoiceItem polja: `id`, `invoice`, `name`, `code`, `quantity`, `unit_price`,
`discount_percentage`, `discounted_amount`, `tax_name`, `tax_rate`,
`total_including_tax`, `product`, `billable_item`.

**Ključna provjera prije svega ostalog:** Cliniko Invoice ima izravan
`appointment` link. Ako klinika stvarno izdaje svoje service-račune kroz
Cliniko billing modul, spajanje appointment↔invoice je trivijalno i 100%
pouzdano te cijela logika iz §3 (cross-system matching sa Solom) postaje
nepotrebna za taj dio. Ako se pravi fiskalni računi ipak izdaju isključivo
kroz Solo (a Cliniko Invoice modul se ne koristi ili se koristi samo interno),
onda je §3 obavezan. Prije razvoja `matching.py` treba jednim testnim pozivom
na `/invoices` utvrditi koji je slučaj u ovoj klinici.

## 2. Solo — entiteti i polja

Baza: `https://api.solo.com.hr`. Auth: `token` kao query parametar (nalazi se
u Solo postavkama servisa nakon prijave) — **nije** header-based auth.
Odgovori su JSON, UTF-8.

### 2.1 Prikaz računa — `GET /racun`
Parametri: `token` (obavezno), `id` (opcionalno — jedan račun),
`stranica` (paginacija, kad ima više od 1000 računa).

Polja u odgovoru (objekt `racun`): `id`, `broj_racuna`, `tip_usluge`,
`tip_racuna`, `tip_kupca`, `kupac_naziv`, `kupac_adresa`, `kupac_oib`,
`usluge[]` (`kpd`, `opis_usluge`, `cijena`, `porez_stopa`, `suma`),
`neto_suma`, `porezi[]` (`stopa`, `osnovica`, `porez`), `bruto_suma`,
`nacin_placanja`, `datum_racuna`, `datum_isporuke`, `datum_uplate`, `iban`,
`valuta_racuna`, `tecaj`, `status`, `pdf`, `message`. Greške: `status: 101`
(neispravan token), `122` (račun ne postoji), `123` (nema izdanih računa).

**Napomena o JIR/ZKI:** dokumentacijska stranica za prikaz računa ih ne
navodi eksplicitno u popisu polja — treba potvrditi na stvarnom testnom
računu točan naziv polja u kojem se vraćaju (ili provjeriti sadrže li se
samo unutar generiranog PDF-a). `solo_client.py` ih čita ako postoje, ali
ne pretpostavlja njihov naziv kao siguran — vidi `SoloInvoice` model, polje
je opcionalno (`nullable`).

### 2.2 Izrada računa — `POST /racun`
Obavezno: `token`, `tip_usluge`, `tip_racuna` (1=R1, 2=R2, 3=bez oznake,
4=Avansni, 5=Ostalo), `tip_kupca`, `nacin_placanja`.

Stavke (indeksirano brojem usluge, počevši od 1 — `usluga` je redni broj
stavke): `opis_usluge_x` (≤500 znakova), `cijena_x` (2 decimale),
`kolicina_x` (4 decimale), `popust_x` (4 decimale), `porez_stopa_x` (0, 5, 13
ili 25), `jed_mjera_x` (≤5 znakova), `kpd_x` (samo B2B/B2G, 8 znakova).

Opcionalno: `kupac_naziv`, `kupac_adresa`, `kupac_oib`, `rok_placanja`,
`datum_isporuke`, `napomene`, `ponavljanje`, `iban`, `jezik_racuna`,
`valuta_racuna`, `tecaj`, `status`.

Ovaj endpoint ne koristimo za analitiku (samo GET je potreban), ali ga
implementiramo jer je preduvjet za preporuku iz §3: ako klinika kasnije
odluči da recepcija pri izdavanju računa upiše Cliniko appointment ID u
`napomene`, matching postaje deterministički.

**Napomena o fiskalizaciji:** od prosinca 2025. Solo sam provodi
fiskalizaciju; parametar `fiskalizacija` se više ne šalje uz `POST /racun`.
`solo_client.py` ga stoga uopće ne izlaže kao argument.

### 2.3 Katalog (usluge/proizvodi)
Dokumentacija potvrđuje samo postojanje `POST`/`GET`/`DELETE` operacija za
katalog, bez detalja o poljima. Ako klinika koristi šifre kataloga u Solu
koje se poklapaju s Cliniko `appointment_type.name`, to bi bila najbolja
dodatna karika za matching — označeno kao poznato proširenje, ne
implementirano dok se stvarni odgovor ne provjeri na test-računu.

## 3. Povezivanje Cliniko ↔ Solo

Solo račun nema polje koje izravno referencira Cliniko appointment ID, pa
matching radimo po pravilima, u ovom redoslijedu (prvo pravilo koje uspije
pobjeđuje):

1. **Eksplicitna referenca** — ako `napomene` sadrži token oblika
   `CLINIKO-<appointment_id>` (konvencija koju `matching.py` traži regexom
   `CLINIKO[-:]?(\d+)`, case-insensitive), spoji 1:1. `confidence = 1.0`,
   `match_method = "exact_reference"`. Napomena: dokumentirana Solo `GET
   /racun` shema (§2.1) ne navodi `napomene` kao polje odgovora — ono je
   potvrđeno samo kao parametar pri `POST /racun`. `solo_client.py` ga
   svejedno čita ako ga API vrati; dok se to ne provjeri na stvarnom
   računu, ovo pravilo praktički neće naći kandidate i matching pada na
   pravilo 2.
2. **Datum + terapeut (preko imena pacijenta) + iznos** — `datum_isporuke`
   (ili `datum_racuna` ako isporuke nema) jednak danu `appointment.starts_at`,
   **i** `bruto_suma` unutar tolerancije (default ±10% ili ±5 EUR, što je
   veće) od `appointment_type.deposit_price` (ili prosječne cijene te
   usluge iz povijesnih podataka ako je точnija), **i** `kupac_naziv`
   fuzzy-poklapa (`rapidfuzz.fuzz.token_sort_ratio`, prag 80) s
   `patient.first_name + " " + patient.last_name`.
   `confidence` raste s brojem poklopljenih kriterija (0.6 za 2 od 3, 0.85
   za sva 3), `match_method = "date_amount_name"`.
3. **Dvosmislenost** — ako više termina istog pacijenta istog dana
   zadovoljava kriterije, nijedan se automatski ne uparuje —
   `match_method = "manual_review"`, `confidence = 0`.
4. **Neuparen račun** — nema kandidata → nije vezan uz Cliniko (može biti
   račun za proizvod, ne uslugu).
5. **Neuparen odrađeni termin** (`appointment_state = COMPLETED`) bez
   ijednog kandidata računa → kandidat za "nije naplaćeno" (poseban KPI,
   vidi §5) — treba ručnu provjeru, ne prihod po defaultu.

Svaki rezultat matchinga sprema se u `appointment_invoice_links` s
`confidence_score` i `match_method`. Samo zapisi s `confidence_score >= 0.7`
ulaze u automatski izračun prihoda; ostalo ide u red za ručnu provjeru
(`report.py` ih izlista posebno, ne prešućuje).

**Preporuka:** ako postoji utjecaj na proces izdavanja Solo računa,
najjednostavnije i najpouzdanije rješenje je da recepcija/terapeut pri
izdavanju računa upiše Cliniko appointment ID u polje `napomene`. To čini
matching potpuno deterministički i ukida potrebu za fuzzy logikom iz
pravila 2–3.

## 4. Interna baza (shema)

Implementirano u `cliniko_solo/models.py` (SQLAlchemy). Zadani engine je
SQLite (nula-konfiguracijski start); `db_url` u configu se može promijeniti
na Postgres bez izmjena koda.

| Tablica | Ključna polja | Napomena |
|---|---|---|
| `businesses` | id (Cliniko id, PK), business_name, city, time_zone_identifier | |
| `practitioners` | id (PK), first_name, last_name, display_name, active | |
| `appointment_types` | id (PK), name, category, duration_in_minutes, deposit_price | |
| `patients` | id (PK), first_name, last_name, label | samo identifikacijski podskup, §1.4 |
| `appointments` | id (PK), business_id, practitioner_id, patient_id, appointment_type_id, starts_at, ends_at, appointment_state, cancellation_reason_description | `appointment_state` je izvedeno polje (§1.5), računa se pri sync-u |
| `daily_availabilities` | id (PK), business_id, practitioner_id, day_of_week, blocks_json | `blocks_json` = serijalizirani `availabilities[]` |
| `solo_invoices` | id (PK, Solo id), broj_racuna, kupac_naziv, kupac_oib, datum_racuna, datum_isporuke, datum_uplate, neto_suma, bruto_suma, nacin_placanja, status, jir, zki | |
| `solo_invoice_items` | id, invoice_id (FK), opis_usluge, cijena, kolicina, porez_stopa, suma | Solo stavke nemaju vlastiti stabilan ID u API odgovoru — generiramo surogat |
| `appointment_invoice_links` | appointment_id (FK), invoice_id (FK), confidence_score, match_method, created_at | rezultat §3 |

## 5. KPI formule (računa `kpi_engine.py`, ne Claude)

Za period `[from, to]` i (opcionalno) filter po `practitioner_id`:

- `available_hours` = Σ po danima u periodu Σ trajanja `availabilities`
  blokova za taj `day_of_week` (minus unavailable blocks — TODO, §1.6)
- `booked_hours` = Σ `duration_in_minutes` za termine sa `starts_at` u
  periodu i `appointment_state IN (BOOKED, COMPLETED, NO_SHOW)` (tj. sve
  osim CANCELLED i ignoriranih)
- `completed_hours` = isto, samo `appointment_state = COMPLETED`
- `cancelled_hours` = `appointment_state = CANCELLED`
- `no_show_hours` = `appointment_state = NO_SHOW`
- `free_hours` = `available_hours - booked_hours` (donja granica 0)
- `utilization` = `completed_hours / available_hours`
- `revenue` = Σ `bruto_suma` matchanih `solo_invoices` (preko
  `appointment_invoice_links` s `confidence_score >= 0.7`) za termine u
  periodu/filteru
- `revenue_per_available_hour` = `revenue / available_hours`
- `revenue_per_completed_hour` = `revenue / completed_hours`
- `unbilled_completed_appointments` = broj COMPLETED termina bez matcha
  (§3, pravilo 5) — signal, ne trpa se automatski u prihod
- `lost_capacity_breakdown` = `{free_hours, cancelled_hours, no_show_hours}`
- `lost_revenue_estimate` = `free_hours * (revenue_per_completed_hour klinike
  ili terapeuta, konfigurabilno)`

Ovo je isključivo deterministički izračun nad podacima iz baze (§4) —
Claude ne dobiva sirove retke termina/računa nego već gotove KPI brojke iz
ove tablice formula, kako je opisano u originalnom prijedlogu arhitekture
(§7 razgovora).
