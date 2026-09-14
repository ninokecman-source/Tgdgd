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
- `max_retry_attempts` – koliko puta ponoviti račun čije slanje nije uspjelo
  prije nego se odustane i javi (zadano 5); vidi "Što se događa kad slanje
  ne uspije" niže
- `cliniko_oib_section` + `cliniko_oib_field` – naziv sekcije i polja na
  kartici pacijenta u kojem klinika drži OIB (zadano "Fiskalizacija" / "OIB");
  vidi "OIB i adresa kupca na računu" niže. Ako to polje ne postoji, OIB se
  nikad ne šalje i skripta radi normalno.
- `cliniko_skip_item_ids` – kataloške stavke koje označavaju da račun NE ide
  u Solo (npr. "R1 račun" za tvrtke); vidi "Računi na tvrtku (R1)" niže
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
- `solo_nacin_placanja_item_ids` – kataloške stavke po kojima skripta
  prepoznaje kartice (3) / gotovinu (2) / transakcijski (1); vidi "Kako se
  određuje način plaćanja" niže. ID-eve dobiješ naredbom
  `python sync.py --list-billable-items`.
- `solo_default_service_description` – opis koji se stavlja na Solo stavku
  **samo ako** stavka na Cliniko računu nema naziv; inače se prenosi stvarni
  naziv usluge (vidi "Što ide na Solo račun" niže)
- `solo_tip_usluge` – ID usluge iz tvog Solo računa. Prijavi se u Solo ->
  **Usluge -> Tipovi usluga**, otvori uslugu koju koristiš za naplatu
  (npr. "Fizioterapija") i uzmi njen ID (vidljiv u URL-u ili detaljima
  usluge). Ako još nemaš definiranu uslugu, prvo je kreiraj tamo.
- `alert_email` – adresa na koju stižu obavijesti kad nešto zapne; vidi
  "Obavijesti kad nešto zapne" niže. Ostaviš li prazno, nitko neće biti
  obaviješten ako fiskalizacija stane.
- `healthcheck_url` – URL vanjskog nadzora koji skripta poziva nakon svakog
  uspješnog prolaza (npr. healthchecks.io). Jedino to može otkriti da je
  server ugašen ili proces mrtav.
- `send_pdf_email` + `smtp_*` – podaci za slanje PDF računa pacijentu; ako
  `send_pdf_email` postaviš na `false`, mail se ne šalje (samo fiskalizacija).
  Zadano je postavljeno za Zoho Mail Pro (`smtppro.zoho.com`, port 465,
  SSL) — `smtp_username`/`smtp_password` treba app-specific lozinku, isto
  kao za glavnu Zoho skriptu u ovom repou. Ako koristiš neki drugi mail
  servis, promijeni `smtp_host`/`smtp_port` (465 = SSL, 587 = STARTTLS —
  oboje je podržano).
- `state_db_path` – gdje se sprema baza obrađenih računa. **Mora biti izvan
  foldera s kodom** (zadano `/var/lib/poprio/state.sqlite3`), jer bi se inače
  izgubila pri sljedećem kopiranju/redeployu koda — a ta baza je jedini zapis
  o tome što je već poslano u Solo. Za lokalno testiranje stavi relativnu
  putanju (npr. `state/test.sqlite3`).

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

## 6. Prvo pokretanje (inicijalizacija)

Skripta **odbija raditi dok joj se ne kaže odakle kreće**. Dok je baza
obrađenih računa prazna, svako pokretanje bez zastavice staje uz jasnu
poruku i ne šalje ništa.

To nije gnjavaža nego zaštita: prazna baza izgleda potpuno isto bez obzira
je li ovo prva instalacija ili je baza izgubljena (preseljen server, Docker
bez trajnog volumena, obrisan folder). Kad bi skripta u toj situaciji sama
pretpostavila "ništa još nije fiskalizirano", već fiskalizirane račune
poslala bi u Solo drugi put — a duplikat fiskalnog računa ispravlja se samo
stornom.

Zato jednom, svjesno, odaberi jedno od dvoje:

```bash
python sync.py --init-from-now      # kreni od sada, ne diraj starije račune
python sync.py --backfill-days 7    # obradi i račune plaćene zadnjih 7 dana
```

`--init-from-now` je pravi odabir nakon preseljenja servera ili gubitka
baze. `--backfill-days` je za prvu instalaciju, kad stvarno želiš da se
obradi i nešto unatrag — **provjeri prije toga koliko plaćenih računa je u
tom prozoru**, jer će za svaki nastati dokument u Solu.

Nakon inicijalizacije, redovni rad je bez zastavica:

```bash
python sync.py          # jedan prolaz (za cron)
python sync.py --loop   # trajno (za systemd/Docker)
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
sudo pip install -r requirements.txt   # sustavski, da ga vidi i korisnik poprio
# (alternativa: virtualenv u /opt/poprio/venv pa u poprio.service
#  ExecStart=/opt/poprio/venv/bin/python /opt/poprio/sync.py --loop)
sudo cp poprio.service /etc/systemd/system/poprio.service
sudo systemctl daemon-reload

# jednokratna inicijalizacija (vidi korak 6) - servis se bez nje neće pokrenuti
sudo -u poprio /usr/bin/python3 /opt/poprio/sync.py --init-from-now

sudo systemctl enable --now poprio
journalctl -u poprio -f   # praćenje logova
```

Baza obrađenih računa živi u `/var/lib/poprio/` — systemd ju kreira i
održava preko `StateDirectory=poprio`, pa preživi restart, reboot i ponovni
deploy koda. **Nemoj ju premještati u `/opt/poprio`**: taj folder se prepiše
pri svakom `scp`-u nove verzije koda.

### b) Docker (ako server već ima Docker, ništa drugo se ne instalira)

```bash
docker build -t poprio .

# jednokratna inicijalizacija (vidi korak 6)
docker run --rm \
    -v $(pwd)/config.json:/app/config.json:ro \
    -v poprio_state:/var/lib/poprio \
    poprio python sync.py --init-from-now

docker run -d --name poprio --restart unless-stopped \
    -v $(pwd)/config.json:/app/config.json:ro \
    -v poprio_state:/var/lib/poprio \
    poprio
docker logs -f poprio
```

Imenovani volumen `poprio_state` **mora** biti montiran u oba poziva — bez
njega baza obrađenih računa nestaje sa svakim restartom kontejnera.

`config.json` se **montira**, ne ugrađuje u image — `.dockerignore` ga
izričito isključuje, jer bi inače ključevi ostali zapečeni u imageu i procurili
svakome tko do njega dođe (npr. push u registry).

### c) cron (alternativa, bez trajnog procesa)

```
* * * * * cd /putanja/do/poprio && /usr/bin/python3 sync.py >> sync.log 2>&1
```

## Oznaka izvornog Cliniko računa

Svaki dokument koji skripta kreira u Solu nosi u napomeni oznaku
`Cliniko #<id>` — npr. `Cliniko #2018168603207010009`. Napomena se
**ispisuje na PDF-u** koji pacijent dobije.

Svrha je mogućnost ručne provjere: ako lokalna baza ikad zakaže ili se
posumnja u duplikat, u Solu se po toj oznaci vidi iz kojeg je Cliniko
računa svaki dokument nastao. Bez nje ta veza ne postoji nigdje osim u
lokalnoj SQLite bazi.

Oznaka se postavlja u `sync.py`, u varijabli `napomene` — ako je ikad ne
želiš na PDF-u, ondje se uklanja (uz gubitak te mogućnosti provjere).

## Samo jedna instanca odjednom

Skripta pri pokretanju uzima zaključavanje na datoteci pored baze
(`state.lock`). Ako je već drži drugi proces, druga kopija ispiše poruku i
ne radi ništa — tako systemd servis uz zaboravljen cron unos, dva
`docker run` ili ručno pokretanje "samo da provjerim" ne mogu poslati isti
račun dvaput.

Uz to se svaki račun **zauzima u bazi prije** slanja u Solo, pa čak i da
dva procesa nekako prođu kroz zaključavanje, kroz zauzimanje može proći
samo jedan (provjereno s 8 paralelnih procesa nad istim računom).

**Zaključavanje vrijedi samo unutar jednog stroja.** Ako se skripta pokrene
na dva različita servera s istim Solo tokenom — npr. stari server ostane
raditi nakon preseljenja — ovo ju neće zaustaviti. Kod preseljenja obavezno
ugasi servis na starom stroju.

## Što ide na Solo račun

U Solo idu **stvarne stavke Cliniko računa**, svaka kao zaseban redak s
vlastitim nazivom, cijenom i količinom. Račun s dva tretmana po 70 € u Solu
ima dva retka, ne jedan zbirni od 140 €.

Pri prijenosu:

- **oznaka načina plaćanja se izbacuje** — ona je pomoćna stavka od 0 €, na
  fiskalnom računu nema što tražiti
- **cijena se pretvara u neto** jer Solo sam dodaje porez (uz stopu 0 to je
  isti iznos)
- **popust se ugrađuje u cijenu** umjesto da se prenosi kao zaseban podatak:
  Solo popust računa u postocima, a Cliniko ga dopušta i u eurima, pa bi
  pretvaranje zbog zaokruživanja lako promijenilo ukupan iznos

  stavka nema naziv

**Iznos se provjerava prije slanja.** Zbroj stavki mora ispasti točno isti
kao ukupan iznos Cliniko računa; ako ne ispadne (izgubljen popust, koncesija,
cent na zaokruživanju), račun se **ne šalje** nego ide među neuspjele i javlja
se mailom. Bolje ne fiskalizirati ništa nego fiskalizirati krivi iznos.

Račun na kojem nakon izbacivanja oznake ne ostane nijedna stavka (npr. netko
je otvorio račun i dodao samo "Gotovinsko plaćanje") označava se kao
**preskočen** — nema se što fiskalizirati, pa se ne ponavlja.

Solo prima najviše **36 stavki** po računu; veći račun se odbija prije slanja,
uz jasnu poruku umjesto Solo-ove šifre greške.

## Računi na tvrtku (R1)

Račun na tvrtku **se ne prenosi u Solo** — izdaje se ručno, izravno u Solu.

Razlog je što Cliniko nema ništa od onoga što Solo traži za B2B račun:

| Solo traži za B2B | Ima li Cliniko |
|---|---|
| naziv tvrtke | samo kao slobodan tekst, bez strukture |
| **OIB tvrtke** (obavezan) | nema polja nigdje — ni na pacijentu ni na kontaktu |
| **KPD šifra po stavci** (obavezna) | ne postoji kao pojam |
| oznaka da je kupac tvrtka (F1 umjesto F2) | nema je |

Umjesto da se to nekako izmišlja, takav račun se u Clinku **označi** i skripta
ga preskače.

### Postavljanje

1. U Clinku kreiraj stavku (Settings → Billable Items) s cijenom **0**, npr.
   **"R1 račun"**
2. `python sync.py --list-billable-items` i prepiši njen ID u config:

```json
"cliniko_skip_item_ids": {
  "R1 račun": "3000000000000000001"
}
```

Ključ lijevo je samo naziv koji će se pojaviti u logu i mailu; možeš dodati i
više takvih oznaka ako zatreba.

### Kako se ponaša

Kad se ta stavka nađe na računu, skripta ga **trajno preskače** (stanje
`skipped`) — ne šalje ga, ne ponavlja i ne čeka oznaku načina plaćanja. Ta se
provjera radi **prva**, prije svega ostalog, jer račun na tvrtku obično nema
ni oznaku načina plaćanja pa bi inače zapeo u čekanju ispravka koji nikad ne
dolazi.

O svakom takvom računu stiže **jedan** mail („račun #120 treba ručno izdati u
Solu"), i to samo jednom — jer osoba koja doda oznaku u Clinku nije nužno ona
koja izdaje račun u Solu. Podsjetnik se ne ponavlja.

Pri pokretanju se provjerava da ta oznaka postoji u Clinku, isto kao oznake
načina plaćanja: ako se ID obriše ili krivo prepiše, račun na tvrtku bi tiho
otišao u Solo kao da je za fizičku osobu.

## Obavijesti kad nešto zapne

Bez ovoga sve završava u logu koji nitko ne gleda — računi se tiho prestanu
fiskalizirati, a otkrije se tek kad knjigovođa usporedi promet. Zato postoje
dvije odvojene stvari, jer pokrivaju različite kvarove:

### 1. Mail obavijesti (`alert_email`)

Skripta šalje mail kad:

- sinkronizacija padne **tri prolaza zaredom** (istekao API ključ, Solo
  nedostupan, pukla mreža) — jedan pad je obično prolazan i ne budi nikoga
- neki račun potroši sve pokušaje i ostane nefiskaliziran
- postoje računi zaustavljeni usred slanja

Isti problem javlja se najviše **jednom u 6 sati**, pa kvar koji traje ne
pošalje stotine mailova. Kad sinkronizacija proradi, stiže jedna obavijest o
oporavku. Koriste se isti `smtp_*` podaci kao za slanje računa pacijentima —
za Zoho treba app-specific lozinka.

Ako `alert_email` ostaviš prazan, skripta pri pokretanju upozori da nitko
neće biti obaviješten ako fiskalizacija stane.

### 2. Vanjski nadzor (`healthcheck_url`)

**Mail ne može javiti da je skripta mrtva** — ugašen server, ubijen proces
ili pukla mreža ne šalju mailove o sebi. Za to treba netko izvana tko
primijeti da se skripta prestala javljati.

Nakon svakog uspješnog prolaza skripta pozove `healthcheck_url`. Besplatan
servis poput [healthchecks.io](https://healthchecks.io) pošalje ti mail kad
ta javljanja prestanu stizati:

1. otvori račun i kreiraj novu provjeru ("check")
2. postavi period na npr. 1 sat uz 30 minuta tolerancije (skripta se javlja
   puno češće, pa to znači "ako se ne javi cijeli sat, nešto ne valja")
3. kopiraj ping URL u `healthcheck_url` u `config.json`

Ako ostaviš prazno, javljanje se preskače — ali tad ništa neće primijetiti
da je server ugašen.

## Što se događa kad slanje ne uspije

Neuspjeli račun **ne ovisi o vremenskom prozoru upita**. Zapisuje se u bazu
i ponavlja po ID-u, pa ga skripta neće izgubiti ni kad oznaka "obrađeno do"
odmakne preko njega (npr. Solo bude nedostupan pola sata, a u međuvremenu
stignu noviji računi).

Svaki račun je u jednom od stanja:

| Stanje | Značenje | Što skripta radi |
|---|---|---|
| `done` | dokument u Solu postoji | ništa više |
| `failed`, pokušaji < `max_retry_attempts` | slanje palo, npr. Solo nedostupan | ponavlja u svakom prolazu |
| `failed`, pokušaji potrošeni | ne ide ni nakon više pokušaja | staje i javlja pri svakom pokretanju |
| `waiting` | nema oznake načina plaćanja | ponavlja neograničeno, javlja mailom |
| `skipped` | nema stavki, ili je označen za preskakanje (R1) | ništa — trajno zatvoren |
| `pending` | proces prekinut **usred** slanja | ne dira — traži ljudsku provjeru |

### Zaglavljeni računi (potrošeni pokušaji)

Skripta ih više ne pokušava sama jer uzrok očito nije prolazan. Log kaže
koja je greška. Kad ukloniš uzrok, vrati ih u red za ponovni pokušaj tako
da im poništiš brojač:

```bash
sudo -u poprio sqlite3 /var/lib/poprio/state.sqlite3 \
  "SELECT cliniko_invoice_id, attempts, last_error FROM processed_invoices WHERE status='failed';"

# nakon što je uzrok riješen - vrati u red
sudo -u poprio sqlite3 /var/lib/poprio/state.sqlite3 \
  "UPDATE processed_invoices SET attempts=0 WHERE cliniko_invoice_id='<id>';"
```

### Zaustavljeni računi (prekid usred slanja)

Ako proces bude prekinut (reboot, OOM, `kill`) točno između zauzimanja
računa i potvrde da je dokument nastao, zapis ostane u stanju `pending`.
Tada se **stvarno ne zna** je li dokument u Solu nastao ili nije, pa ga
skripta neće sama ponoviti (mogao bi nastati duplikat fiskalnog računa)
nego to javi pri svakom pokretanju.

Razrješava se ručno — provjeri postoji li u Solu dokument s napomenom
`Cliniko #<id>`:

```bash
# koji su zaustavljeni
sudo -u poprio sqlite3 /var/lib/poprio/state.sqlite3 \
  "SELECT cliniko_invoice_id FROM processed_invoices WHERE status='pending';"

# dokument POSTOJI u Solu -> račun je fiskaliziran, označi zapis gotovim
sudo -u poprio sqlite3 /var/lib/poprio/state.sqlite3 \
  "UPDATE processed_invoices SET status='done' WHERE cliniko_invoice_id='<id>';"

# dokumenta NEMA u Solu -> vrati ga u red za slanje
sudo -u poprio sqlite3 /var/lib/poprio/state.sqlite3 \
  "UPDATE processed_invoices SET status='failed', attempts=0
   WHERE cliniko_invoice_id='<id>' AND status='pending';"
```

Zapis se vraća u stanje `failed` s poništenim brojačem, **ne briše se** —
tako ga sljedeći prolaz dohvaća po ID-u kroz mehanizam ponovnih pokušaja,
neovisno o tome je li oznaka "obrađeno do" već odmakla preko njega. Obrisan
zapis bi se mogao poslati samo ako je račun još unutar vremenskog prozora.

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
smisla ako je pacijent primijeti na svom računu, npr. "Način plaćanja:
Kartica", "Način plaćanja: Gotovina", "Način plaćanja: Transakcijski".

Zatim pokreni:

```bash
python sync.py --list-billable-items
```

Ispisat će cijeli katalog s ID-evima; stavke s cijenom `0.00` su tvoje tri
oznake. Prepiši njihove **ID-eve** u `solo_nacin_placanja_item_ids`:

```json
"solo_nacin_placanja_item_ids": {
  "3": "2030716998274516377",
  "2": "2030716647605536151",
  "1": "2030716822734505368"
}
```

(Solo kod: 1=transakcijski, 2=gotovina, 3=kartice, 4=ček, 5=ostalo — ključ
lijevo je Solo kod, vrijednost desno je ID Cliniko stavke koja mu odgovara.)

**Zašto ID, a ne šifra ili naziv:** Cliniko šifre (`item_code`) dodjeljuje
iz istog brojčanog niza kojim numerira i obične usluge — oznake su dobile
`18`/`19`/`20` jer su bile sljedeće slobodne. Neka buduća usluga mogla bi
dobiti isti broj i skripta bi je pročitala kao oznaku plaćanja te je izbacila
s računa. ID je trajan, jedinstven, i preživi preimenovanje stavke.

Pri svakom pokretanju skripta provjeri da te tri stavke stvarno postoje i
ispiše na što se koji Solo kod veže:

```
  oznaka kartice: 'Kartično plaćanje' (0.00 EUR)
  oznaka gotovina: 'Gotovinsko plaćanje' (0.00 EUR)
  oznaka transakcijski: 'Transkacijsko plaćanje' (0.00 EUR)
```

Ako neka nedostaje (obrisana ili krivi ID u configu), javlja se mailom —
jer bi inače svi takvi računi tiho išli sa zadanim načinom plaćanja.

### Svakodnevna upotreba

Kod zatvaranja svakog Cliniko računa, osoblje doda odgovarajuću stavku
načina plaćanja uz uslugu (npr. "Fizioterapijski tretman" + "Način
plaćanja: Gotovina"). Skripta dohvaća stavke računa
(`GET /invoices/{id}/invoice_items`) i traži onu koja dolazi iz jedne od tri
kataloške stavke iz configa. Oznaka **ne ide** na Solo dokument i ne utječe
na iznos.

### Kad oznake nema

Račun bez oznake se **ne fiskalizira** — skripta ne pogađa način plaćanja.
Pogrešan način plaćanja na fiskalnom računu ispravlja se samo stornom, pa je
čekanje jeftinije od nagađanja.

Takav račun ide u stanje `waiting` i:

- **ponavlja se neograničeno**, bez trošenja pokušaja — ispravak radi čovjek
  i može potrajati danima
- **čim netko u Clinku doda oznaku, račun se fiskalizira sam** pri sljedećem
  prolazu, s ispravnim načinom plaćanja; ništa se ne mora ručno pokretati
- javlja se **mailom s popisom brojeva računa** koje treba ispraviti (npr.
  „račun #87, čeka od 2026-09-14"), najviše jednom dnevno za isti popis —
  novi račun na popisu javlja se odmah

Bez tog maila osoblje ne bi imalo kako saznati: skripta ne može ništa
upisati natrag u Cliniko, a log nitko ne gleda.

**Prije puštanja u pogon (posebno ako je `solo_document_type: "racun"`):**
napravi par test računa u Clinku sa svakom od tri stavke i provjeri da
skripta u logu ispravno prijavi odgovarajući način plaćanja — pogrešan
`nacin_placanja` na stvarnom `racun`-u znači formalni storno + novi račun,
ne tihu ispravku.

### Tijek ispravka u praksi

Osoblje propust primijeti **u Solu** — računa jednostavno nema. Tada otvore
taj račun u Clinku i dodaju stavku načina plaćanja; skripta ga pri sljedećem
prolazu fiskalizira sama. Mail s popisom računa koji čekaju je drugi kanal za
isto, koristan kad nitko ne gleda Solo.

Oznaka se može dodati i na račun koji je **već označen plaćenim** — to je
ustaljena praksa i ispravak je moguć naknadno.

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

**Ime** dolazi iz imena i prezimena pacijenta. Ako pacijent u Clinku nema
upisano ime, na računu piše **"Klijent"** i to se javlja u logu — ime kupca
nije obavezno na računu fizičkoj osobi, ali polje mora biti popunjeno.

**Adresa** dolazi iz standardnih Cliniko polja na kartici pacijenta
(Address 1/2, Post code, City) — ništa se ne treba podešavati.

**OIB nije obavezan** na računu fizičkoj osobi i većina pacijenata ga neće
imati upisanog. Popunjava se samo kad pacijent traži OIB na računu (npr. za
dopunsko osiguranje ili poreznu olakšicu). Račun bez OIB-a je posve uredan.

### Postavljanje polja za OIB u Clinku

Cliniko nema ugrađeno polje za OIB, pa se koristi vlastito polje na kartici
pacijenta. U Clinku pod **Settings → Patient details / Custom fields**
kreiraj sekciju **"Fiskalizacija"** s tekstualnim poljem **"OIB"**. Ako ih
nazoveš drugačije, uskladi `cliniko_oib_section` i `cliniko_oib_field` u
`config.json`.

Dok to polje ne postoji, OIB se jednostavno nikad ne šalje — skripta radi
normalno.

### Provjera ispravnosti

Upisani OIB se prije slanja provjerava kontrolnom znamenkom (ISO 7064,
MOD 11,10). Ako ne prođe — tipfeler, zamijenjene znamenke, kriva duljina —
**račun se svejedno fiskalizira, ali bez OIB-a**, uz upozorenje u logu koje
imenuje pacijenta i spornu vrijednost.

Razlog: krivi OIB na fiskalnom računu ispravlja se stornom, dok je račun bez
OIB-a za fizičku osobu uredan. Blokirati fiskalizaciju zbog tipfelera bilo bi
skuplje od izostavljanja podatka.

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

## Poznata ograničenja

Stvari koje su svjesno ostavljene ovakve — nisu kvarovi, ali je dobro znati za
njih prije nego iznenade:

- **Zaokruživanje kad se uključi PDV.** Uz stopu 0 (trenutno) ne može se
  dogoditi. Uz stopu različitu od nule, kod količine veće od 1 i iznosa koji se
  ne dijeli čisto, cijena po jedinici zaokružena na dvije decimale može dati
  ukupan iznos koji odstupa za cent. Takav račun **neće biti fiskaliziran** —
  provjera iznosa ga odbije i javi, pa se pogleda ručno.
- **Više poslovnica u Clinku.** Ako klinika ikad ima više „businessa", svi
  njihovi računi fiskaliziraju se u isti Solo račun, bez razlikovanja.
  Postaje bitno tek kad se otvori druga lokacija.
- **Ispravak u Clinku nakon fiskalizacije.** Ako se račun u Clinku izmijeni
  ili obriše *nakon* što je već poslan u Solo, skripta to ne prati — Solo
  zadržava stari podatak. Fiskalni dokument se ionako ispravlja samo stornom,
  pa se to radi u Solu.
- **Podijeljeno plaćanje** (dio gotovinom, dio karticom) nije podržano; na
  računu smije biti samo jedna oznaka načina plaćanja.

## Napomena o privatnosti

Skripta iz Clinika u Solo šalje samo ono što je potrebno za račun: ime i
adresu pacijenta, OIB ako postoji, te **nazive, cijene i količine usluga s
tog računa** (npr. "Fizioterapijski tretman", 60,00 x 1) — dakle isto ono
što bi pisalo na računu koji pacijent ionako dobiva. Dijagnoze, bilješke
terapeuta i ostali medicinski podaci se nikad ne dohvaćaju ni ne šalju.
