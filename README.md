# Proprio WhatsApp ↔ Cliniko

Vlastita integracija koja pacijentima Proprio Centra šalje **WhatsApp podsjetnik dan prije termina**
iz Clinikoa, prima njihove odgovore (gumbi *Potvrđujem* / *Trebam promjenu*) i recepciji daje
jednostavnu stranicu s pregledom.

- Bez vanjskih biblioteka – samo Node.js 22.13+ (ugrađeni SQLite, HTTP, Intl). Nema `npm install`.
- Postojeći WhatsApp Business broj **ostaje u aplikaciji na mobitelu** (coexistence preko 360dialoga).
- Testirano: 13 automatskih testova (`npm test`), uključujući promjenu sata, duplikate, potpis webhooka.

---

## 1. Kako radi

```
            svaki sat 10–19 h                       odobreni predložak
 Cliniko  ───────────────────►  ovaj servis  ─────────────────────────►  WhatsApp  ──►  pacijent
 (sutrašnji termini, API)       (mali server)  ◄─────────────────────────  (360dialog)  ◄── gumb / odgovor
                                     │                webhook
                                     ├── baza (SQLite): tko je dobio, isporuka, odgovor
                                     └── /status  → stranica za recepciju
```

1. Svaki sat od 10 do 19 h servis iz Clinikoa uzme **sutrašnje** termine (individualne i grupne).
2. Preskače otkazane, arhivirane i "did not arrive" termine.
3. Za svakog pacijenta šalje **jedan** podsjetnik (za najraniji termin tog dana) – samo ako:
   - ima mobilni broj (fiksni broj nema WhatsApp),
   - ima privolu (vidi poglavlje 5).
4. Ista poruka se **nikad ne šalje dvaput**. Ako se termin premjesti na drugo vrijeme, pacijent dobije novi podsjetnik.
5. Kad pacijent klikne gumb, servis to zabilježi, po želji pošalje kratki automatski odgovor
   i (opcionalno) upiše napomenu u termin u Clinikou.
6. Sve ostale poruke pacijenata recepcija i dalje vidi i odgovara **u aplikaciji na mobitelu**.

Poruka pacijentu (predložak):

> Poštovani/a **Ana**, podsjećamo Vas na termin u Proprio Centru **četvrtak, 1. listopada** u **09:00** h. Molimo potvrdite dolazak.
> [Potvrđujem] [Trebam promjenu]

---

## 2. Što treba pripremiti (jednom)

| # | Što | Gdje | Tko |
|---|-----|------|-----|
| 1 | Verificirana tvrtka u Meti | business.facebook.com → Sigurnosni centar | admin |
| 2 | 360dialog račun + spajanje postojećeg broja (coexistence) | hub.360dialog.com | admin |
| 3 | 360dialog API ključ | 360dialog Hub → broj → API key | admin |
| 4 | Odobren predložak `podsjetnik_termin` (hr, UTILITY) | WhatsApp Manager ili 360dialog Hub | admin |
| 5 | Cliniko API ključ | Cliniko → My Info → Manage API keys | admin |
| 6 | Mali server u EU + (pod)domena, npr. `wa.proprio.hr` | npr. Hetzner Cloud, DNS kod registrara | informatičar |

### 2.1 Spajanje broja preko 360dialoga (coexistence)
1. Registrirajte se na **hub.360dialog.com** (izravni klijent) i odaberite plan.
2. Pokrenite spajanje broja, prijavite se Meta računom tvrtke i odaberite opciju za **postojeći
   WhatsApp Business app broj** (coexistence). U aplikaciji na mobitelu potvrdite povezivanje
   (obično skeniranjem QR koda) i po želji dozvolite prijenos povijesti poruka.
3. Uvjeti: aplikacija WhatsApp Business novija verzija, broj aktivno korišten barem 7 dana,
   aplikaciju na mobitelu **otvoriti barem svakih 13 dana** (inače se veza prekida).
4. U Hubu generirajte **API ključ** za broj → to je `D360_API_KEY`.

### 2.2 Predložak poruke
U WhatsApp Manageru (business.facebook.com → WhatsApp Manager → Predlošci) ili u 360dialog Hubu:

- Naziv: `podsjetnik_termin` · Kategorija: **Utility** · Jezik: **Croatian (hr)**
- Tijelo:
  `Poštovani/a {{1}}, podsjećamo Vas na termin u Proprio Centru {{2}} u {{3}} h. Molimo potvrdite dolazak.`
- Primjeri varijabli: `Ana` · `četvrtak, 1. listopada` · `09:00`
- Gumbi (Quick reply): `Potvrđujem` i `Trebam promjenu`

Ako tekst gumba promijenite, isto upišite u `.env` (`WA_BUTTON_CONFIRM`, `WA_BUTTON_CHANGE`).
**Ne dodavati** nikakve promotivne rečenice ni zdravstvene podatke (vrstu terapije, dijagnozu).

### 2.3 Cliniko API ključ
1. Preporuka: u Clinikou otvorite zasebnog korisnika, npr. "WhatsApp integracija".
2. Prijavljeni kao taj korisnik: **My Info → Manage API keys → Add an API key**.
3. Ključ završava oznakom poslužitelja (npr. `...-uk1`) – servis je sam prepoznaje.
4. Ako želite upis potvrda u napomene termina (`CLINIKO_WRITE_NOTES=true`), korisnik mora smjeti uređivati termine.

---

## 3. Instalacija na server (Ubuntu 24.04, npr. Hetzner CX22 u Njemačkoj/Finskoj)

```bash
# 1) Node.js 22 LTS
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs caddy     # caddy: vidi caddyserver.com/docs/install ako ga nema u apt-u
node -v                                  # mora biti 22.13 ili noviji

# 2) Korisnik i kod
sudo useradd --system --create-home --shell /usr/sbin/nologin proprio
sudo mkdir -p /opt/proprio-whatsapp-cliniko
# kopirajte sadržaj ove mape u /opt/proprio-whatsapp-cliniko (scp, rsync ili git)
sudo mkdir -p /opt/proprio-whatsapp-cliniko/data
sudo chown -R proprio:proprio /opt/proprio-whatsapp-cliniko

# 3) Postavke
cd /opt/proprio-whatsapp-cliniko
sudo -u proprio cp .env.example .env
sudo -u proprio nano .env                # popunite (poglavlje 4)
sudo chmod 600 .env
sudo -u proprio cp consent.example.txt consent.txt

# 4) Provjera
sudo -u proprio npm run check            # ✔ Cliniko ... ✔ WhatsApp ...
sudo -u proprio npm run preview          # što bi se poslalo sutra – NIŠTA ne šalje

# 5) HTTPS + servis
# DNS: A zapis wa.proprio.hr -> IP servera
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # zamijenite domenu
sudo systemctl reload caddy
sudo cp deploy/proprio-whatsapp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now proprio-whatsapp
journalctl -u proprio-whatsapp -f         # logovi
```

### 3.1 Webhook (da odgovori pacijenata stižu u servis)
U `.env` postavite `WEBHOOK_PATH` na dugu nasumičnu putanju, npr.
`/whatsapp/webhook/7f3c9a1e5b2d4c8f9e0a` (generirajte s `openssl rand -hex 16`), pa je prijavite 360dialogu:

```bash
curl -X POST https://waba-v2.360dialog.io/v1/configs/webhook \
  -H "D360-API-KEY: VAŠ_KLJUČ" -H "Content-Type: application/json" \
  -d '{"url":"https://wa.proprio.hr/whatsapp/webhook/7f3c9a1e5b2d4c8f9e0a"}'
```
Dugačka tajna putanja štiti webhook – 360dialog ne potpisuje poruke, pa je putanja jedina zaštita.

---

## 4. Postavke (`.env`)

Sve je opisano u `.env.example`. Najvažnije:

| Varijabla | Značenje |
|-----------|----------|
| `CLINIKO_API_KEY` | API ključ iz Clinikoa |
| `CLINIKO_USER_AGENT` | Naziv + **ispravan e-mail**, npr. `Proprio WhatsApp podsjetnici (info@proprio.hr)` – Cliniko inače blokira |
| `CLINIKO_INCLUDE_GROUP` | `true` = i grupni programi |
| `CLINIKO_WRITE_NOTES` | `true` = potvrda pacijenta upisuje se u napomenu termina |
| `D360_API_KEY` | API ključ iz 360dialog Huba |
| `WA_TEMPLATE_NAME` / `WA_TEMPLATE_LANG` | točno kao u odobrenom predlošku |
| `CONSENT_MODE` | `allowlist` (pilot), `custom_field` (rad), `all` |
| `REMINDER_HOURS` | sati slanja, zadano `10-19` |
| `REMINDER_DAYS_AHEAD` | `1` = podsjetnik dan prije |
| `STATUS_TOKEN` | lozinka za stranicu recepcije |
| `TEST_PHONE` | ako je upisan, **sve** poruke idu na taj broj (za testiranje) |
| `DRY_RUN` | `true` = ništa se ne šalje |

---

## 5. Privola pacijenata (GDPR + pravila WhatsAppa)

WhatsApp traži da pacijent pristane primati poruke na WhatsApp. Tri načina:

- **`allowlist` – za pilot.** U `consent.txt` upišite ID pacijenta ili broj mobitela, jedan po retku.
- **`custom_field` – za redovni rad (preporuka).** U Clinikou dodajte prilagođeno polje pacijenta
  (Settings → Custom fields), npr. potvrdni okvir **"WhatsApp podsjetnici"** s jednom opcijom
  "Pacijent pristaje", ili radio gumbe Da/Ne. Recepcija ga označi pri prvom dolasku.
  Naziv polja mora biti isti kao `CONSENT_FIELD_NAME`.
- **`all`** – svi s mobitelom. Ne preporučuje se bez pravne provjere.

Ostalo:
- U poruci su samo ime, datum i sat – **nikakvi zdravstveni podaci**.
- Slobodan tekst pacijenata servis **ne sprema**; zapisi se brišu nakon `RETENTION_DAYS` (zadano 90 dana).
- U logovima su brojevi djelomično skriveni (`38598***4567`).
- Dopunite politiku privatnosti i evidenciju obrade (Meta i 360dialog kao izvršitelji obrade, DPA s 360dialogom).

---

## 6. Puštanje u rad – preporučeni redoslijed

1. U Clinikou napravite **testnog pacijenta** sa svojim mobitelom i zakažite mu lažni termin za sutra.
   `CONSENT_MODE=allowlist`, u `consent.txt` samo njegov broj → `npm run preview`, pa `npm run send`.
   Provjerite tekst, datum, sat i gumbe; kliknite gumb i pogledajte `/status`. Termin zatim otkažite.
2. U `consent.txt` dodajte 10–20 pacijenata (djelatnici, stalni pacijenti) → 1–2 tjedna.
3. Dodajte polje privole u Cliniko, `CONSENT_MODE=custom_field`.
4. U Clinikou isključite SMS podsjetnike za pacijente koji dobivaju WhatsApp (ili ih ostavite kao rezervu).

Nakon svake promjene `.env`: `sudo systemctl restart proprio-whatsapp`.

---

## 7. Svakodnevno korištenje

- **Recepcija:** `https://wa.proprio.hr/status?token=STATUS_TOKEN` (spremite kao oznaku u pregledniku).
  Prikazuje danas, sutra i prekosutra. **Označeni redovi** = nazvati pacijenta
  (nema mobitela, nema privole, poruka nije isporučena ili pacijent traži promjenu).
- **Ručno slanje / provjera (na serveru):**
  ```bash
  npm run preview -- --date=2026-10-01    # što bi se poslalo za taj dan
  npm run send -- --date=2026-10-01       # pošalji (preskače već poslane)
  npm run status -- --date=2026-10-01     # tablica zapisa
  ```
- **Zdravlje servisa:** `https://wa.proprio.hr/health` (može se dodati u besplatni uptime monitor).

---

## 8. Najčešći problemi

| Simptom | Uzrok | Rješenje |
|---------|-------|----------|
| `Cliniko API 401` | krivi ili opozvan API ključ | novi ključ u Clinikou |
| `Cliniko API 403` / blokada | User-Agent bez e-maila | ispraviti `CLINIKO_USER_AGENT` |
| `WhatsApp 132001` | predložak ne postoji / nije odobren / kriv jezik | provjeriti naziv i `hr` u WhatsApp Manageru |
| `WhatsApp 132000` | broj varijabli ne odgovara | predložak mora imati točno {{1}} {{2}} {{3}} |
| `WhatsApp 131026` | broj nema WhatsApp | recepcija nazove; ispraviti broj u Clinikou |
| `WhatsApp 131047` | slobodna poruka nakon 24 h | automatski odgovori šalju se samo odmah nakon klika – normalno ne bi smjelo |
| `WhatsApp 131049/131048` | Meta ograničila poruke / pacijenti blokiraju | provjeriti privole i tekst |
| Veza s aplikacijom na mobitelu prekinuta | aplikacija neotvorena > 13 dana | otvoriti aplikaciju; ponovno spojiti u 360dialog Hubu |
| Mnogo "nema mobitela" | broj upisan kao fiksni ili neispravno | ispraviti broj u Clinikou (tip "Mobile") |
| Odgovori se ne bilježe | webhook nije prijavljen ili kriva putanja | ponoviti korak 3.1, `journalctl -u proprio-whatsapp -f` |

Detaljan katalog grešaka: `whatsapp_business_integracija_klinika.txt` (poglavlje 6).

---

## 9. Struktura koda

```
src/
  server.js     HTTP server (webhook, /status, /health) + raspored slanja
  cli.js        naredbe: check, reminders, status
  reminders.js  dohvat termina, odabir pacijenata, slanje
  cliniko.js    Cliniko API klijent (paginacija, 429 limit, User-Agent)
  whatsapp.js   slanje predloška/teksta preko 360dialoga, ponavljanje kod privremenih grešaka
  webhook.js    statusi isporuke, odgovori pacijenata
  consent.js    privola (allowlist / Cliniko polje)
  phone.js      normalizacija hrvatskih brojeva, prepoznavanje mobitela
  time.js       vremenska zona Europe/Zagreb, promjena sata, hrvatski datumi
  db.js         SQLite baza (ugrađena u Node.js)
  status.js     stranica za recepciju
test/           automatski testovi (npm test) s lažnim Cliniko i WhatsApp serverom
deploy/         systemd servis i Caddy (HTTPS)
```
