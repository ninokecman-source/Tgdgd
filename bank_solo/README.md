# Bankovni izvod -> Solo ponude (uplate Emmett tečajeva)

Skripta čita dnevne bankovne izvode (Erste banka, `.wri` prilog) koji stižu
na Zoho mail, prepoznaje ulazne uplate, uspoređuje ime u retku transakcije
s polaznicima iz Excel tablica prijava (koje generira `zoho_to_excel.py`), i
za svaku uparenu uplatu izdaje **Solo ponudu** (quote, ne fiskalizirani
račun) na točno uplaćeni iznos. Uplaćeni iznos se automatski zbraja u
"Payment Received" koloni odgovarajućeg Excel retka (npr. akontacija 100 +
kasnija doplata 300 = 400 ukupno).

Ime uplatitelja se ne čita s točno određene pozicije u izvodu (format za to
nije bio dovoljno pouzdano potvrđen) — umjesto toga se **cijeli tekst
retka** transakcije pretražuje za bilo koju poznatu kombinaciju
ime+prezime (ili prezime+ime) iz Excel tablica. Ako se ime ne prepozna,
uplata se preskače uz upozorenje u ispisu **i mail obavijest** (na
`notify_email`) — tu treba ručna provjera. Svaka neuparena uplata javlja
se mailom samo **jednom** (ne ponavlja se svako pokretanje).

Svaka transakcija (po jedinstvenoj referenci) i svaki mail se obrađuju
točno jednom (SQLite stanje u `state_db_path`), pa ponovno pokretanje ne
stvara duplikate.

Na ponudu se šalje i **adresa** i **OIB** polaznika. Adresa dolazi iz
Excel tablice (već se tamo sprema). OIB se **ne** sprema u Excel (Emmett
predložak nema stupac za to) — umjesto toga se svaki put kad zatreba
dohvati izravno iz izvorne Zoho prijave tog polaznika (pretraga po email
adresi kroz INBOX + Split/Zagreb foldere). Ako OIB nije pronađen, ponuda
se ipak šalje (bez OIB-a), uz upozorenje u ispisu.

## 1. Instalacija

```bash
cd bank_solo
pip install -r requirements.txt
```

## 2. Konfiguracija

```bash
cp config.example.json config.json
```

Popuni u `config.json`:

- `zoho_email`, `zoho_app_password`, `imap_host` – isti podaci kao za
  glavnu Zoho skriptu u root folderu (ista adresa prima i bankovne izvode)
- `bank_sender` – adresa s koje banka šalje izvode
  (`netbanking.support@erstebank.hr`)
- `imap_folder` – folder u kojem se nalaze bankovni izvodi (`Izvodi`)
- `sender_filter` – adresa pošiljatelja prijava (`prijava@emmett-hr.com`),
  koristi se za pronalaženje izvorne prijave radi dohvaćanja OIB-a
- `course_folder_roots` – isti Zoho folderi kao u glavnoj skripti
  (`["Split", "Zagreb"]`) koji se pretražuju (uz INBOX) pri traženju OIB-a
- `excel_dir` – folder s Excel tablicama prijava (isti `output_dir` kao u
  glavnoj Zoho skripti)
- `smtp_host`, `smtp_port` – za slanje mail obavijesti o neuparenim
  uplatama (ista Zoho SMTP postavka kao za auto-potvrde u glavnoj skripti)
- `notify_email` – adresa na koju stižu obavijesti o neuparenim uplatama
  (obično ista kao `zoho_email`)
- `solo_api_token` – Solo API token (Solo -> Postavke -> API)
- `solo_tip_kupca` – **1** (potvrđeno u Solo API dokumentaciji = fizička
  osoba/B2C, to odgovara polaznicima)
- `solo_tip_usluge` – **2** (šira kategorija usluge - ista za sve Emmett
  tečajeve, isto što koristi i postojeća Cliniko integracija). Ovo NIJE
  isto što i "Ak"/"M12"/... šifre iz Solo Kataloga - to su zasebne stavke
  s vlastitom cijenom u Solo-u, dok `tip_usluge` API poziv traži samo
  kao klasifikacijsku kategoriju; konkretan naziv tečaja ide u opis
  stavke (`course_description_map` ispod)
- `solo_nacin_placanja` – **1** (potvrđeno u Solo API dokumentaciji =
  "Transakcijski račun", to je bankovni transfer)
- `solo_default_tax_rate` – **0** (prema tvojoj listi usluga, svi Emmett
  tečajevi su na 0% PDV)
- `deposit_amount` – iznos akontacije (100)
- `deposit_description` – opis stavke kad uplaćeni iznos odgovara
  akontaciji
- `course_description_map` – opis stavke po kodu tečaja (M1&2, M3, M4,
  M5, M6, Ponavljanje M6 i Praktičarski dan) - ovo je već popunjeno
  nazivima iz tvog Solo kataloga
- `state_db_path` – gdje se sprema baza obrađenih transakcija/mailova (ne
  treba dirati)

### Kako skripta bira opis stavke

Ako je uplaćeni iznos jednak `deposit_amount` (100) — koristi se
`deposit_description` (Akontacija). Inače se kod tečaja polaznika (iz
Excel tablice) traži u `course_description_map` i koristi odgovarajući
naziv. Ako kod tečaja nije u mapi, uplata se preskače uz upozorenje.

**Napomena:** `config.json` sadrži tajne podatke i nikad se ne smije
commitati (već je u `.gitignore`).

## 3. Pokretanje

```bash
python3 sync.py
```

Ispis pokazuje svaku upararenu uplatu (kome, koliko, koja Solo ponuda je
izdana) i svaku neuparenu uplatu koja treba ručnu provjeru.

## 4. Automatsko pokretanje (cron)

Isti pristup kao za `zoho_to_excel.py` — pokreće se na tvom Macu:

```
0 */6 * * * cd /putanja/do/ovog/foldera/bank_solo && /usr/bin/python3 sync.py >> sync.log 2>&1
```

Preporučeno je pokretati **nakon** što se `zoho_to_excel.py` pokrenula
(ili barem redovito), da Excel tablice s polaznicima budu ažurne prije
uparivanja uplata.

## Prije prvog pravog slanja

1. Ovaj modul uvijek šalje **ponude** (quote), nikad fiskalizirane
   račune — nema JIR/ZKI, sigurno za testiranje.
2. Provjeri barem jednu uplatu ručno u Solo sučelju nakon prvog
   pokretanja — ime kupca, iznos, opis, ispravna usluga.
3. Ako neka uplata ostane neuparena (ime nije prepoznato), otvori
   `sync.log` da vidiš cijeli redak transakcije i provjeri zašto (npr.
   polaznik možda još nije upisan u Excel, ili banka koristi neočekivan
   format imena).

## Uplate vs isplate

S izvoda se uzimaju **samo uplate**. Smjer nosi **dvoznamenkasti kod tipa
transakcije** na početku retka — `20` je uplata, `10` isplata. Predznak
iznosa ne znači ništa: u stvarnim izvodima i uplate i isplate imaju `+`.

Da se smjer ne bi mogao krivo pročitati, **svaki izvod se provjerava protiv
vlastitog salda**. Redak `907` sadrži ukupan iznos uplata i ukupan iznos
isplata; oba se moraju poklopiti s pročitanim transakcijama. Ako se ne
poklope — npr. banka uvede novi kod tipa — izvod se **ne obrađuje**, mail
ostaje neoznačen za idući pokušaj, a razlog piše u logu. Bolje propuštena
uplata nego kriva ponuda u Solu.

Kodovi koji se broje kao uplata podešavaju se s `credit_type_codes`
(default `["20"]`). Nepoznat kod se broji kao isplata, pa provjera salda
odmah javi da nešto ne štima.

Iz svakog retka čitaju se i ime uplatitelja, IBAN, mjesto i opis plaćanja,
sve s točnih pozicija. Polaznik se traži u imenu uplatitelja **i u opisu
plaćanja** — bitno kad tečaj plaća firma, a ime polaznika stoji samo u
opisu.

Što je koji izvod pročitao vidiš s:

```bash
python3 diagnose.py --izvod
```

## Na čije ime ide uplata

Ljudi plaćaju i za druge — kolegica za kolegicu, roditelj za dijete — pa
ime uplatitelja nije nužno ime polaznika. Zato je mjerodavan **opis
plaćanja**:

1. Ako opis spominje točno jednog polaznika iz tablica, uplata ide njemu.
   Ako to nije uplatitelj, u logu stoji upozorenje da se vidi.
2. Ako opis spominje više poznatih imena, a jedno od njih je uplatitelj
   (npr. „Zrinka Smoje uplata za Ana Horvat"), uzima se onaj drugi —
   uplatitelj je već poznat iz svog polja.
3. Ako opis nikoga ne spominje, gleda se ime uplatitelja — uobičajen
   slučaj kad netko plaća sam za sebe.
4. Ako se ne može pouzdano odlučiti, uplata se **ne knjiži**: stiže ti
   mail o neuparenoj uplati i riješiš je ručno.

Zato je važno da u opisu plaćanja stoji ime polaznika. To se traži i u
automatskom odgovoru na prijavu („Opis plaćanja: … + Vaše ime i prezime").

## Kada se izvod obrađuje, a kada ne

Svaki izvod se prije obrade provjerava protiv retka sa saldom (907), koji
nosi ukupne uplate i ukupne isplate za taj dan.

- **Zbroj pročitanih uplata mora se poklopiti do lipe.** Ako se ne poklapa,
  znači da je neka ulazna transakcija promakla ili je krivo pročitana —
  izvod se **ne obrađuje**, mail ostaje neoznačen i pokušava se ponovno.
  Radije propuštena uplata nego kriva ponuda u Solu.
- **Neslaganje samo u isplatama ne zaustavlja obradu**, nego ide kao
  upozorenje u log. Ako se uplate poklapaju točno, nijedna ulazna
  transakcija nije promakla — nepročitano je nešto odlazno (bankovna
  naknada, kartica), što na ponude nema nikakvog utjecaja. Bez toga bi
  jedna nepročitana naknada trajno blokirala knjiženje svih uplata.

Transakcijski redak se prepoznaje po kodu `905` na kraju i dvoznamenkastom
kodu tipa na početku (`20` uplata, `10` isplata). Prije se tražio i oblik
IBAN-a odmah iza koda tipa, pa su ispadali redci koji IBAN nemaju —
bankovne naknade i kartična plaćanja — i cijeli izvod bi ostao neobrađen.

Ako izvod nema upotrebljiv redak 907, ne obrađuje se — bez njega se nema
čime provjeriti je li pročitan ispravno.

Da vidiš kako parser čita konkretan izvod:

```bash
python3 diagnose.py --izvod --koliko 3
```

Da vidiš koje su uplate već proknjižene (tko, koliko, koja Solo ponuda):

```bash
python3 diagnose.py --proknjizeno
```

## Nepovezane uplate (`rijesi_uplatu.py`)

Uplata se ne prepozna kad u opisu plaćanja ne piše ime polaznika: netko
plati za drugoga, upiše samo "tečaj", ili iskrivi ime.

Takva uplata sada **ostaje zapisana** u tablici `unmatched_transactions`,
s iznosom, datumom, uplatiteljem, opisom i razlogom. Dosad se pamtila samo
njezina oznaka (`notified_unmatched`), pa su podaci ostajali jedino u mailu
upozorenja - a izvod se čita točno jednom. Tko nije prepoznat tog trena,
za sustav više nije ni postojao, iako je novac stvarno stigao.

```bash
python3 bank_solo/rijesi_uplatu.py --popis
python3 bank_solo/rijesi_uplatu.py --ref 1234567 --email ana@primjer.hr
python3 bank_solo/rijesi_uplatu.py --ref 1234567 --email ana@primjer.hr --stvarno
```

Bez `--stvarno` je samo pregled: pokaže na koga bi uplata išla, u koju
tablicu i koji redak, i što bi pisalo na ponudi.

S `--stvarno` se dogodi isto što i kod automatske obrade, istim redom:

1. izda se Solo ponuda na uplaćeni iznos (OIB se dohvaća iz izvorne
   prijave; ako se do maila ne može, ponuda ide bez OIB-a)
2. iznos se pribroji u koloni "Payment Received"
3. transakcija se označi obrađenom i makne iz nepovezanih

Tablica se dira tek nakon što ponuda prođe - ako Solo zakaže, uplata nije
ni proknjižena, pa se pokušaj može ponoviti bez dvostrukog knjiženja. Uplata
koja je već povezana odbija se izrijekom.

Polaznik se bira po **email adresi**, jer je ona jedina jedinstvena. Ako se
ista adresa pojavi na više tečajeva, skripta odustaje i traži da to riješiš
ručno - ne pogađa.

Isto se radi i s mobitela, tipkom **Poveži** na stranici Uplate
(vidi `web/README.md`).

## Potvrda uplate polazniku

Čim se uplata upari i proknjiži, polazniku se javlja da je zaprimljena.
Uključuje se s `"send_payment_confirmation": true`.

Tekst se bira prema tome **što je ta uplata pokrila**:

| Uplata | Dokument s tekstom |
|---|---|
| 2400 € (`course_total_price`) | `potvrda uplate program.docx` — cijeli program, svi moduli |
| 400 € (`price_total`) odjednom | `potvrda uplate modul.docx` — kotizacija za tečaj podmirena |
| 300 € nakon akontacije (ukupno 400) | `potvrda uplate doplata.docx` — doplata, kotizacija podmirena |
| 100 € akontacija | `potvrda uplate akontacija.docx` — potvrda + koliko preostaje |

Dokumenti stoje uz Excel tablice (`excel_dir`), isto kao podsjetnici —
uređuju se u Wordu, vidi „Tekstovi poruka u Word dokumentima" u glavnom
READMEu. Ako prvi redak glasi `Naslov: …`, to je naslov maila.

Redoslijed provjere je odozgo prema dolje, pa uplata cijelog programa ne
završi kao „kotizacija za tečaj podmirena".

Placeholderi: `{first_name}`, `{last_name}`, `{course_code}`, `{location}`,
`{dates}`, `{datumi_rijecima}` („3. i 4. listopada 2026."), `{iznos}`
(ova uplata), `{ukupno_uplaceno}`, `{preostalo}`, `{cijena}`,
`{cijena_tecaja}`, `{instructor_name}`.

Redoslijed je: **dokument → `config.json` → ugrađeni tekst**. Tekstovi su
ugrađeni u skriptu, pa potvrde rade i prije nego napišeš ijedan dokument;
`python3 napravi_predloske.py` ti ih izradi od postojećih tekstova. U logu
uz svaku potvrdu piše odakle je tekst uzet.

Cijene se čitaju iz `price_total` (jedan modul, 400) i `course_total_price`
(cijeli program, 2400). Bez `price_total` se ne može znati preostaje li još
nešto, pa se uvijek šalje tekst za podmirenu kotizaciju.

**Uplata cijelog programa upisuje se u tablicu tog jednog modula.** Iznos
od 2400 € tako uđe u „Payment Received" tečaja na koji je polaznik
prijavljen, pa taj Total Income izgleda veći nego što tečaj vrijedi.
Poruka polazniku je točna, ali knjigovodstveno to treba raspodijeliti
ručno po modulima.

Potvrda se šalje **nakon** knjiženja i izdavanja ponude, i njezin neuspjeh
ne ruši obradu — uplata ostaje proknjižena, a greška se zapiše u log (pa je
donese i provjera logova).
