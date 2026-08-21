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
uplata se preskače uz upozorenje u ispisu — tu treba ručna provjera.

Svaka transakcija (po jedinstvenoj referenci) i svaki mail se obrađuju
točno jednom (SQLite stanje u `state_db_path`), pa ponovno pokretanje ne
stvara duplikate.

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
- `excel_dir` – folder s Excel tablicama prijava (isti `output_dir` kao u
  glavnoj Zoho skripti, npr. `/Users/ninokecman/Desktop/Prijave`)
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
