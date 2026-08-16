# Cliniko -> Solo (automatska fiskalizacija plaćenih računa)

Skripta periodički provjerava Cliniko za novoplaćene (status "Paid") račune i
za svaki od njih kreira fiskalizirani račun u Solo-u. Nakon uspješne
fiskalizacije, pacijentu se mailom šalje PDF računa iz Solo-a (Cliniko ne
šalje paralelno svoj račun).

Svaki Cliniko račun se šalje u Solo **točno jednom** — obrađeni ID-jevi se
pamte u lokalnoj SQLite bazi (`state_db_path`), pa ponovno pokretanje ne
stvara duplikate.

## 1. Instalacija

```bash
cd cliniko_solo
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
- `solo_api_token` – Solo API token (korak 3)
- `solo_tip_racuna`, `solo_tip_kupca`, `solo_nacin_placanja`,
  `solo_default_tax_rate` – **provjeri s knjigovođom** prije prvog pravog
  slanja; zadane vrijednosti (`tip_kupca=1` znači B2C/fizička osoba,
  `nacin_placanja=3` znači kartice, 25% PDV) odgovaraju dogovoru za
  Stripe/Apple Pay/Google Pay naplate, ali svakako testiraj jedan račun
  ručno prije puštanja u pogon
- `solo_tip_usluge` – ID usluge iz tvog Solo računa. Prijavi se u Solo ->
  **Usluge -> Tipovi usluga**, otvori uslugu koju koristiš za naplatu
  (npr. "Fizioterapija") i uzmi njen ID (vidljiv u URL-u ili detaljima
  usluge). Ako još nemaš definiranu uslugu, prvo je kreiraj tamo.
- `send_pdf_email` + `smtp_*` – podaci za slanje PDF računa pacijentu; ako
  `send_pdf_email` postaviš na `false`, mail se ne šalje (samo fiskalizacija)
- `state_db_path` – gdje se sprema baza obrađenih računa (ne treba dirati)

**Napomena:** `config.json` sadrži tajne podatke i nikad se ne smije
commitati (već je u `.gitignore`).

## 5. Prvo pokretanje

Kod prvog pokretanja skripta po defaultu gleda samo račune plaćene u
zadnjih 10 minuta (da se slučajno ne fiskaliziraju stari računi). Ako želiš
obraditi i starije plaćene račune kod prvog pokretanja:

```bash
python sync.py --backfill-days 7
```

Za redovno korištenje:

```bash
python sync.py
```

## 6. Automatsko pokretanje (cron)

```
*/2 * * * * cd /putanja/do/ovog/foldera/cliniko_solo && /usr/bin/python3 sync.py >> sync.log 2>&1
```

Ovo mora raditi na serveru/cloud instanci koja je stalno uključena (ne na
tvom računalu) — vidi glavni README repozitorija za kontekst.

## Napomena o privatnosti

Skripta iz Clinika u Solo šalje samo ono što je potrebno za račun (ime
pacijenta, email, iznos, PDV, način plaćanja). Dijagnoze, bilješke
terapeuta i ostali medicinski podaci se nikad ne dohvaćaju ni ne šalju.
