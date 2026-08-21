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
- `solo_tip_kupca` – tip kupca (1 = fizička osoba/B2C, provjeri s
  knjigovođom ako nisi siguran)
- `solo_tip_usluge` – ID usluge za Emmett tečajeve iz Solo sučelja
  (Usluge -> Tipovi usluga) — **treba popuniti prije prvog pokretanja**
- `solo_nacin_placanja` – Solo kod za način plaćanja "transakcijski
  račun/žiro" (bankovni transfer) — **provjeri točan broj u Solo sučelju
  ili s knjigovođom prije prvog pravog slanja**, pogrešan kod će odbiti
  zahtjev
- `solo_default_tax_rate` – stopa PDV-a (25 = zadano za HR)
- `solo_service_description` – opis stavke na ponudi (vidljiv kupcu)
- `state_db_path` – gdje se sprema baza obrađenih transakcija/mailova (ne
  treba dirati)

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

1. Ostavi `solo_document_type` na ponudi (ovaj modul uvijek šalje ponude,
   ne fiskalizirane račune) dok ne budeš siguran da su podaci ispravni.
2. Provjeri barem jednu uplatu ručno u Solo sučelju nakon prvog
   pokretanja — ime kupca, iznos, opis.
3. Ako neka uplata ostane neuparena (ime nije prepoznato), otvori
   `sync.log` da vidiš cijeli redak transakcije i provjeri zašto (npr.
   polaznik možda još nije upisan u Excel, ili banka koristi neočekivan
   format imena).
