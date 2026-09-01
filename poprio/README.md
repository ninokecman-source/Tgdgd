# Poprio — Cliniko -> Solo (automatska fiskalizacija plaćenih računa)

Skripta prati Cliniko za novoplaćene ("Paid") račune i za svaki od njih
odmah kreira fiskalizirani račun u Solo-u — praktički u istom trenutku kad
je pacijent platio u Clinku. Nakon uspješne fiskalizacije, pacijentu se
mailom šalje PDF računa iz Solo-a (Cliniko ne šalje paralelno svoj račun).
Stvarni način plaćanja (kartica/gotovina/transakcijski) prepoznaje se iz
posebne stavke od 0 EUR koju osoblje doda na Cliniko račun — vidi "Kako se
određuje način plaćanja" niže za postavljanje i razlog zašto je taj korak
bitan.

Svaki Cliniko račun se šalje u Solo **točno jednom** — obrađeni ID-jevi se
pamte u lokalnoj SQLite bazi (`state_db_path`), pa ponovno pokretanje ili
pad servisa ne stvara duplikate.

Radi kao **poll**, ne webhook: skripta svakih par desetaka sekundi pita
Cliniko "ima li novih plaćenih računa" umjesto da čeka da Cliniko nešto
pošalje njoj. To znači da nije potreban javni HTTPS endpoint, provjera
potpisa webhooka ni otvaranje ulaznih portova — server treba samo izlazni
internet pristup, što je najjednostavnije za pokrenuti na jeftinoj vanjskoj
instanci (vidi "Pokretanje na vanjskom serveru" niže). Uz zadani `poll_interval_seconds: 15` kašnjenje je u praksi svega par
sekundi. Cliniko dopušta 200 zahtjeva/min po korisniku, a svaki prazan
prolaz (nema novih plaćenih računa) košta samo 1 zahtjev, pa se interval
može spustiti i niže (npr. 5-10s) bez rizika od rate-limita — Solo-ovo
ograničenje od ~5s vrijedi samo za stvarno kreiranje računa, ne za
provjeru ima li novih.

## 1. Instalacija

```bash
cd poprio
pip install -r requirements.txt
```

## 2. Cliniko API ključ

1. Prijavi se u Cliniko -> klikni na svoje ime -> **My info**.
2. Uključi "Allow yourself to create and use API keys" i spremi.
3. Vrati se na My info -> **Manage API keys** -> **Add an API Key**.
4. Kopiraj ključ odmah (prikazuje se samo jednom). Ključ na kraju ima
   nastavak koji označava shard (npr. `-eu2`) — skripta ga sama prepoznaje,
   ne treba ništa dodatno podešavati.

Cliniko API ključ daje pristup zdravstvenim podacima pacijenata — čuvaj ga
kao lozinku i nikad ga ne commitaj u git.

## 3. Solo API token

Prijavi se u Solo -> Postavke -> API, i kopiraj svoj API token.

## 4. Konfiguracija

```bash
cp config.example.json config.json
```

Popuni u `config.json`:

- `cliniko_api_key` – Cliniko API ključ (korak 2)
- `cliniko_user_agent` – naziv aplikacije + tvoj mail (Cliniko to traži u
  svakom zahtjevu)
- `poll_interval_seconds` – koliko često (u sekundama) skripta u `--loop`
  modu provjerava Cliniko za nove plaćene račune (zadano 15; može i niže,
  vidi gore)
- `solo_api_token` – Solo API token (korak 3)
- `solo_document_type` – `"racun"` (zadano) kreira odmah fiskalizirani
  račun; `"ponuda"` kreira nefiskalni nacrt koji se ručno pretvara u Solo
  sučelju (sigurnija opcija ako ne vjeruješ da će stavka za način plaćanja
  iz "Kako se određuje način plaćanja" niže uvijek biti ispravno dodana)
- `solo_tip_racuna`, `solo_tip_kupca`, `solo_default_tax_rate` –
  **provjeri s knjigovođom** prije prvog pravog slanja; zadano
  `tip_kupca=1` znači B2C/fizička osoba, a `solo_default_tax_rate=0` znači
  bez PDV-a (Solo API prihvaća 0/5/13/25 kao stopu). Ako si ipak u sustavu
  PDV-a, promijeni na stvarnu stopu (npr. 25).
- `solo_nacin_placanja_item_codes` + `solo_nacin_placanja_default` – kako
  skripta bira kartice (3) / gotovinu (2) / transakcijski (1), po
  računu, vidi "Kako se određuje način plaćanja" niže
- `solo_tip_usluge` – ID usluge iz tvog Solo računa. Prijavi se u Solo ->
  **Usluge -> Tipovi usluga**, otvori uslugu koju koristiš za naplatu
  (npr. "Fizioterapija") i uzmi njen ID (vidljiv u URL-u ili detaljima
  usluge). Ako još nemaš definiranu uslugu, prvo je kreiraj tamo.
- `send_pdf_email` + `smtp_*` – podaci za slanje PDF računa pacijentu; ako
  `send_pdf_email` postaviš na `false`, mail se ne šalje (samo fiskalizacija).
  Zadano je postavljeno za Zoho Mail Pro (`smtppro.zoho.com`, port 465,
  SSL) — `smtp_username`/`smtp_password` treba app-specific lozinku, isto
  kao za glavnu Zoho skriptu u ovom repou. Ako koristiš neki drugi mail
  servis, promijeni `smtp_host`/`smtp_port` (465 = SSL, 587 = STARTTLS —
  oboje je podržano).
- `state_db_path` – gdje se sprema baza obrađenih računa (ne treba dirati)

**Napomena:** `config.json` sadrži tajne podatke i nikad se ne smije
commitati (već je u `.gitignore`).

## 5. Fiskalizacija mora biti postavljena u Solo web sučelju

Ako pri slanju dobiješ grešku "Odabrani način plaćanja za ovog kupca
zahtijeva fiskalizaciju...", to znači da u Solo web sučelju, pod
**Postavke -> Fiskalizacija**, još nisu uneseni certifikat, poslovnica i
operater. To je jednokratno ručno podešavanje u Solo-u (nema veze s ovom
skriptom ni s API tokenom) — bez toga Solo ne može izdati fiskalizirani
račun za plaćanja karticom/gotovinom.

**Zašto je bitno da je način plaćanja točan prije slanja:** Solo
**fiskalizira `racun` odmah pri kreiranju** (JIR/ZKI se dodjeljuju u tom
trenutku) — polje `status` (Otvoreno/Poslano/Plaćeno) je samo
knjigovodstvena oznaka i na to ne utječe. `racun` se, drugim riječima, ne
može "kreirati, a fiskalizirati kasnije". Zato skripta način plaćanja ne
pogađa iz teksta nego ga čita iz strukturirane stavke na Cliniko računu —
vidi "Kako se određuje način plaćanja" niže — a ako i dalje ne vjeruješ da
će ta stavka uvijek biti dodana, `"solo_document_type": "ponuda"` je
sigurnija alternativa (ponuda se nikad ne fiskalizira, pa netočan
`nacin_placanja` na njoj nema fiskalne posljedice; ti/osoblje je onda
ručno pretvorite u Solo sučelju, birajući tad stvarni način plaćanja).

## 6. Prvo pokretanje

Kod prvog pokretanja skripta po defaultu gleda samo račune plaćene u
zadnjih 10 minuta (da se slučajno ne fiskaliziraju stari računi). Ako želiš
obraditi i starije plaćene račune kod prvog pokretanja:

```bash
python sync.py --backfill-days 7
```

Za ručnu provjeru jednog prolaza (npr. kroz cron):

```bash
python sync.py
```

## 7. Pokretanje na vanjskom serveru

Skripta mora raditi na serveru/cloud instanci koja je stalno uključena (ne
na tvom računalu) — dva jednako jednostavna načina, biraj jedan:

### a) systemd servis (bez cron-a, preporučeno)

`sync.py --loop` sam interno čeka `poll_interval_seconds` između prolaza,
pa je dovoljan jedan trajni proces:

```bash
scp -r poprio/ korisnik@server:/opt/poprio
ssh korisnik@server
cd /opt/poprio && cp config.example.json config.json   # pa popuni config.json
sudo useradd --system --home /opt/poprio --shell /usr/sbin/nologin poprio
sudo chown -R poprio:poprio /opt/poprio
pip install -r requirements.txt   # ili u virtualenv, prilagodi ExecStart u poprio.service
sudo cp poprio.service /etc/systemd/system/poprio.service
sudo systemctl daemon-reload
sudo systemctl enable --now poprio
journalctl -u poprio -f   # praćenje logova
```

### b) Docker (ako server već ima Docker, ništa drugo se ne instalira)

```bash
docker build -t poprio .
docker run -d --name poprio --restart unless-stopped \
    -v $(pwd)/config.json:/app/config.json \
    -v poprio_state:/app/state \
    poprio
docker logs -f poprio
```

### c) cron (alternativa, bez trajnog procesa)

```
* * * * * cd /putanja/do/poprio && /usr/bin/python3 sync.py >> sync.log 2>&1
```

## Kako se određuje način plaćanja

Cliniko-ov javni API **ne šalje** način plaćanja kao posebno polje na
računu (istraženo uživo, ne samo iz dokumentacije — vidi "Zašto ne
napomena/API" niže). Umjesto toga, osoblje na svaki Cliniko račun uz
stvarnu uslugu doda **jednu dodatnu stavku od 0 EUR** koja označava kojim
je načinom pacijent platio — ista radnja kao dodavanje bilo koje druge
usluge na račun, samo jedan dodatni klik.

### Jednokratno postavljanje u Clinku

U Cliniko **Settings -> Billable Items** kreiraj tri stavke (proizvod ili
uslugu, po tvom izboru), svaku s cijenom **0** i jasnim nazivom da ima
smisla ako je pacijent primijeti na svom računu, npr.:

| Naziv u Clinku | Item code | Cijena |
|---|---|---|
| Način plaćanja: Kartica | `KART` | 0 |
| Način plaćanja: Gotovina | `GOT` | 0 |
| Način plaćanja: Transakcijski | `TRAN` | 0 |

**Item code** polje je bitno — po njemu skripta prepoznaje stavku, ne po
nazivu (naziv možeš mijenjati kasnije bez utjecaja na skriptu). Uskladi
kodove s `solo_nacin_placanja_item_codes` u `config.json`:

```json
"solo_nacin_placanja_item_codes": {
  "3": "KART",
  "2": "GOT",
  "1": "TRAN"
}
```

(Solo kod: 1=transakcijski, 2=gotovina, 3=kartice, 4=ček, 5=ostalo — ključ
lijevo je Solo kod, vrijednost desno je Cliniko item code koji mu
odgovara.)

### Svakodnevna upotreba

Kod zatvaranja svakog Cliniko računa, osoblje doda odgovarajuću stavku
načina plaćanja uz uslugu (npr. "Fizioterapijski tretman" + "Način
plaćanja: Gotovina"). Skripta dohvaća stavke računa
(`GET /invoices/{id}/invoice_items`), traži onu čiji `code` odgovara
jednom od kodova u configu (točno podudaranje, case-insensitive), i
koristi pripadajući Solo kod. Stavka od 0 EUR **ne utječe** na iznos koji
ide u Solo (Solo dobiva samo stvarnu uslugu, ne i marker).

Ako nijedna stavka na računu ne odgovara nijednom kodu, koristi se
`solo_nacin_placanja_default`, uz upozorenje u ispisu (`journalctl -u
poprio` ili `sync.log`) — to je znak da je osoblje zaboravilo dodati
stavku na taj račun.

**Prije puštanja u pogon (posebno ako je `solo_document_type: "racun"`):**
napravi par test računa u Clinku sa svakom od tri stavke i provjeri da
skripta u logu ispravno prijavi odgovarajući način plaćanja — pogrešan
`nacin_placanja` na stvarnom `racun`-u znači formalni storno + novi račun,
ne tihu ispravku.

**Napomena o vidljivosti:** ta stavka od 0 EUR pojavljuje se i na
Clinikovom vlastitom PDF računu koji pacijent može zatražiti (kao redak
"Način plaćanja: Gotovina — 0,00€") — zato joj daj jasan naziv, ne
kriptičnu šifru.

### Zašto ne napomena/API

Cliniko PDF prikazuje način plaćanja u sekciji "Payment Details" (npr.
"Gotovina"), ali taj podatak **nije dostupan preko API-ja** — testirano na
stvarnom, plaćenom Cliniko računu:
- puni JSON objekt računa (svih dokumentiranih i nedokumentiranih polja)
  nema nikakvo polje za način plaćanja; `notes` i `patient_extra_information`
  su prazni čak i kad PDF pokazuje "Gotovina"
- `/patient_payments`, `/payments`, `/invoices/{id}/payments`,
  `/invoices/{id}/patient_payments` — sve vraćaju `404 Not Found`
- nema webhookova za invoice/payment evente u javnom API-ju
- `online_payment_url` (javni link s računa) za već plaćen račun prikazuje
  samo "already been paid", bez detalja o plaćanju
- ni `Attendee` ni `Booking`/`Appointment` sheme nemaju polje za Stripe/
  procesor plaćanja — samo `booking_ip_address`/`online_booking_policy_accepted`,
  koji govore je li termin rezerviran online, ne je li i **plaćen** online
- PDF/print izvoz i "Payments Summary" izvještaj postoje samo kroz
  prijavljenu web sesiju, nisu dokumentiran API endpoint — dohvat bi
  zahtijevao spremanje stvarne Cliniko lozinke na server i automatizaciju
  preglednika (Playwright), što je lomljivo (puca čim Cliniko promijeni
  sučelje) i rizičnije od API ključa

Zato je stavka od 0 EUR na računu (`invoice_items`, dokumentiran i
pouzdan endpoint) najbolji dostupan signal — strukturiran odabir iz
Clinikovog popisa usluga, ne slobodan upis teksta.

## OIB i adresa kupca na računu

Skripta automatski šalje u Solo i OIB i adresu pacijenta, ako postoje:

- **Adresa** dolazi iz standardnih Cliniko polja na kartici pacijenta
  (Address 1/2, Post code, City) — ništa dodatno ne treba podesiti.
- **OIB** dolazi iz custom field sekcije **"Fiskalizacija"**, polje
  **"OIB"**, na kartici pacijenta u Clinku (to polje se u Clinku prikazuje
  samo kad je ispunjeno). Ako pacijent nema upisan OIB, račun se svejedno
  šalje — samo bez tog podatka.

**Napomena:** Cliniko javno ne dokumentira točan naziv JSON ključeva unutar
custom field zapisa (`label` vs `name`, `response` vs `value`) — kod u
`sync.py::extract_oib` provjerava obje varijante, ali svakako **testiraj na
jednom stvarnom pacijentu s upisanim OIB-om** prije nego se osloniš na ovo.
Ako OIB ne stigne u Solo, ispiši `patient["custom_fields"]` za tog
pacijenta (u `run_once()`, odmah nakon `cliniko.get_patient(...)`) i
prilagodi ključeve u `extract_oib`.

## Poznata svojstva Solo API-ja

Otkriveno testiranjem na živom Solo računu, ugrađeno u `solo_client.py`:

- `usluga` mora ići kao ponovljeno polje (jedno po stavci računa), ne samo
  implicitno kroz indeksirane `opis_usluge_N` ključeve
- `cijena_N` i `popust_N` moraju koristiti **zarez** kao decimalni
  separator (npr. `"76,00"`), ne točku
- `popust_N` je obavezan po stavci čak i kad je 0
- `tip_kupca` mora biti broj (1 = B2C), ne string
- `tip_usluge` (ID tipa usluge iz Solo računa) je obavezan
- `porez_stopa_N` prihvaća samo 0, 5, 13 ili 25 (posto) — nema posebnog
  parametra za "nisam u sustavu PDV-a"; za to se koristi `0`
- Solo traži barem ~5 sekundi između API poziva — `solo_client.py` sam
  ugrađeno čeka (`MIN_SECONDS_BETWEEN_REQUESTS`), ne treba ništa ručno
  regulirati
- Cliniko `total_amount` je bruto iznos (s PDV-om); Solo `cijena_N` očekuje
  neto iznos i sam dodaje PDV, pa `sync.py` računa unatrag
  (`net = gross / (1 + porez/100)`) da bruto iznos u Solo-u ispadne isti
  kao plaćeni iznos u Clinku

## Napomena o privatnosti

Skripta iz Clinika u Solo šalje samo ono što je potrebno za račun (ime
pacijenta, email, iznos, PDV, način plaćanja). Stavke računa
(`invoice_items`) se dohvaćaju samo da se pronađe marker načina plaćanja
(`code` polje) — sadržaj/naziv stvarnih usluga se ne prosljeđuje u Solo,
tamo ide `solo_default_service_description` iz configa. Dijagnoze,
bilješke terapeuta i ostali medicinski podaci se nikad ne dohvaćaju ni ne
šalju.
