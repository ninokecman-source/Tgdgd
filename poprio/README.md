# Poprio — Cliniko -> Solo (automatska priprema računa za fiskalizaciju)

Skripta prati Cliniko za novoplaćene ("Paid") račune i za svaki od njih
odmah kreira **Solo ponudu** (nefiskalni nacrt, s istim kupcem/OIB-om/
adresom/iznosom) — praktički u istom trenutku kad je pacijent platio u
Clinku. Ponuda **nije fiskalni dokument** (nema JIR/ZKI); ti ili osoblje je
zatim u Solo sučelju pretvorite u pravi fiskalizirani račun, birajući tad
stvarni način plaćanja (kartica/gotovina/transakcijski) — vidi "Zašto
ponuda, a ne odmah račun" niže za razlog. Skripta automatski šalje
PDF pacijentu mailom **samo** kad je stvarno kreiran fiskalizirani račun
(`solo_document_type: "racun"`), nikad za ponudu.

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
- `solo_document_type` – `"ponuda"` (zadano, preporučeno) ili `"racun"`;
  vidi "Zašto ponuda, a ne odmah račun" niže prije mijenjanja
- `solo_tip_racuna`, `solo_tip_kupca`, `solo_default_tax_rate` –
  **provjeri s knjigovođom** prije prvog pravog slanja; zadano
  `tip_kupca=1` znači B2C/fizička osoba, a `solo_default_tax_rate=0` znači
  bez PDV-a (Solo API prihvaća 0/5/13/25 kao stopu). Ako si ipak u sustavu
  PDV-a, promijeni na stvarnu stopu (npr. 25).
- `solo_nacin_placanja_keywords` + `solo_nacin_placanja_default` – kako
  skripta bira kartice (3) / gotovinu (2) / transakcijski (1), po
  računu, vidi "Način plaćanja po računu" niže
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

## 5. Zašto ponuda, a ne odmah račun

Solo **fiskalizira `racun` odmah pri kreiranju** (JIR/ZKI se dodjeljuju u
tom trenutku, ako je fiskalizacija postavljena) — polje `status`
(Otvoreno/Poslano/Plaćeno) je samo knjigovodstvena oznaka i ne utječe na
to je li dokument već fiskaliziran. Drugim riječima, `racun` se ne može
"kreirati, a fiskalizirati kasnije" — zato je bitno da je način plaćanja
točan **prije** slanja.

Kako Cliniko API ne šalje stvarni način plaćanja po računu (vidi "Način
plaćanja po računu" niže), zadano ponašanje (`solo_document_type:
"ponuda"`) izbjegava taj rizik: ponuda se **nikad ne fiskalizira**, pa
netočan `nacin_placanja` na njoj nema fiskalne posljedice. Skripta odradi
sav ostali ručni unos odmah (kupac, OIB, adresa, iznos, PDV), a ti/osoblje
u Solo sučelju otvorite ponudu, potvrdite/ispravite stvarni način plaćanja
i pretvorite je u pravi fiskalizirani račun — taj jedan klik ostaje svjesna
ljudska potvrda umjesto automatskog nagađanja.

Ako u tvojoj praksi svi automatski sinkronizirani računi dosljedno idu
istim, poznatim načinom plaćanja (npr. isključivo kartica kroz online
booking), možeš postaviti `"solo_document_type": "racun"` da se odmah
fiskalizira bez međukoraka — u tom slučaju `solo_nacin_placanja_default`
mora biti točno taj način, jer se ovdje više ne ispravlja naknadno.

Bez obzira na način rada, prvo mora biti postavljena fiskalizacija u Solo
web sučelju, pod **Postavke -> Fiskalizacija** (certifikat, poslovnica,
operater) — bez toga Solo ne može izdati fiskalizirani `racun` (na `ponuda`
ne utječe, jer se ona nikad ne fiskalizira).

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

## Način plaćanja po računu

Cliniko-ov javni API **ne šalje** način plaćanja kao posebno polje na
računu (nema ga u `Invoice` objektu, niti postoji zaseban `payments`
endpoint) — zato skripta način plaćanja prepoznaje iz teksta **napomene
(`notes`)** na Cliniko računu, na temelju `solo_nacin_placanja_keywords` u
`config.json`:

```json
"solo_nacin_placanja_keywords": {
  "3": ["kartic", "card"],
  "2": ["gotovin", "cash"],
  "1": ["transakcij", "transfer", "virman", "IBAN"]
}
```

Za svaki ključ (Solo kod: 1=transakcijski, 2=gotovina, 3=kartice,
4=ček, 5=ostalo) navedi popis riječi/dijelova riječi koje se mogu pojaviti
u napomeni tog Cliniko računa (usporedba je case-insensitive, traži se kao
podniz). Prvi kod čija se ijedna riječ pronađe u napomeni se koristi.

Ako napomena ne sadrži nijednu poznatu riječ, koristi se
`solo_nacin_placanja_default`, uz upozorenje u ispisu (`journalctl -u
poprio` ili `sync.log`) — to je znak da tekst napomene na tom računu ne
odgovara ključnim riječima u configu, pa ih po potrebi proširi.

**Prije puštanja u pogon provjeri na par stvarnih računa** da napomena u
Clinku doista sadrži prepoznatljiv tekst za svaki način plaćanja koji
koristiš — ako osoblje piše nešto drugačije (npr. "kes" umjesto "gotovina"),
dodaj tu riječ u odgovarajuću listu.

**Zašto ovo mora ići kroz napomenu (istraženo uživo, ne samo iz
dokumentacije):** Cliniko PDF prikazuje način plaćanja u sekciji "Payment
Details" (npr. "Gotovina"), ali taj podatak **nije dostupan preko API-ja**
— testirano na stvarnom, plaćenom Cliniko računu:
- puni JSON objekt računa (svih dokumentiranih i nedokumentiranih polja)
  nema nikakvo polje za način plaćanja; `notes` i `patient_extra_information`
  su prazni čak i kad PDF pokazuje "Gotovina"
- `/patient_payments`, `/payments`, `/invoices/{id}/payments`,
  `/invoices/{id}/patient_payments` — sve vraćaju `404 Not Found`
- nema webhookova za invoice/payment evente u javnom API-ju
- `online_payment_url` (javni link s računa) za već plaćen račun prikazuje
  samo "already been paid", bez detalja o plaćanju
- PDF/print izvoz postoji samo kroz prijavljenu web sesiju, nije
  dokumentiran API endpoint — dohvat bi zahtijevao spremanje stvarne
  Cliniko lozinke na server i automatizaciju preglednika (Playwright), što
  je lomljivo (puca čim Cliniko promijeni sučelje) i rizičnije od API
  ključa, pa je odbačeno u korist pretrage `notes` polja.

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
pacijenta, email, iznos, PDV, način plaćanja). Dijagnoze, bilješke
terapeuta i ostali medicinski podaci se nikad ne dohvaćaju ni ne šalju.
