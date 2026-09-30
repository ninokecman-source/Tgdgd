# Proprio WhatsApp ↔ Cliniko

Vlastita integracija koja pacijentima Proprio Centra šalje **WhatsApp podsjetnik dan prije termina**
iz Clinikoa, prima njihove odgovore (gumbi *Potvrđujem* / *Trebam promjenu*) i recepciji daje
stranicu s porukama pacijenata (inbox s odgovaranjem) i pregledom podsjetnika.

- Bez vanjskih biblioteka – samo Node.js 22.13+ (ugrađeni SQLite, HTTP, Intl). Nema `npm install`.
- Šalje se **izravno preko Meta WhatsApp Cloud API-ja**, bez posrednika. Broj klinike prelazi s aplikacije
  na mobitelu na API (poglavlje 2.1).
- Testirano: 21 automatski test (`npm test`), uključujući promjenu sata, duplikate, potpis webhooka i inbox.

---

## 1. Kako radi

```
            svaki sat 10–19 h                       odobreni predložak
 Cliniko  ───────────────────►  ovaj servis  ─────────────────────────►  WhatsApp  ──►  pacijent
 (sutrašnji termini, API)       (mali server)  ◄─────────────────────────  (Meta API)   ◄── gumb / odgovor
                                     │                webhook
                                     ├── baza (SQLite): tko je dobio, isporuka, odgovor
                                     └── /status  → recepcija: poruke pacijenata + pregled podsjetnika
```

1. Svaki sat od 10 do 19 h servis iz Clinikoa uzme **sutrašnje** termine (individualne i grupne).
2. Preskače otkazane, arhivirane i "did not arrive" termine.
3. Za svakog pacijenta šalje **jedan** podsjetnik (za najraniji termin tog dana) – samo ako:
   - ima mobilni broj (fiksni broj nema WhatsApp),
   - ima privolu (vidi poglavlje 5).
4. Ista poruka se **nikad ne šalje dvaput**. Ako se termin premjesti na drugo vrijeme, pacijent dobije novi podsjetnik.
5. Kad pacijent klikne gumb, servis to zabilježi, po želji pošalje kratki automatski odgovor
   i (opcionalno) upiše napomenu u termin u Clinikou. Ako pacijent umjesto gumba napiše poruku,
   prepoznaju se samo jasni slučajevi („Dolazim”, „Ne mogu doći”, „Otkazujem”); poruka s nijekanjem
   nikad se ne bilježi kao potvrda.
6. Sve poruke pacijenata stižu u **inbox na stranici recepcije** (`/status`) – broj više nije u aplikaciji
   na mobitelu. Recepcija ih čita i odgovara unutar 24 h od zadnje poruke pacijenta (pravilo WhatsAppa);
   nakon toga pacijenta treba nazvati. Slike, glasovne poruke i dokumenti se ne prikazuju – samo
   napomena da su stigli.

Poruka pacijentu (predložak):

> Poštovani/a **Ana**, podsjećamo Vas na termin u Proprio Centru **četvrtak, 1. listopada** u **09:00** h. Molimo potvrdite dolazak.
> [Potvrđujem] [Trebam promjenu]

---

## 2. Što treba pripremiti (jednom)

| # | Što | Gdje | Tko |
|---|-----|------|-----|
| 1 | Verificirana tvrtka u Meti | business.facebook.com → Sigurnosni centar | admin |
| 2 | Meta aplikacija + broj prebačen na Cloud API (poglavlje 2.1) | developers.facebook.com | admin |
| 3 | Trajni token, Phone number ID, App secret | Business Settings, App Dashboard | admin |
| 4 | Odobren predložak `podsjetnik_termin` (hr, UTILITY) | WhatsApp Manager | admin |
| 5 | Cliniko API ključ | Cliniko → My Info → Manage API keys | admin |
| 6 | Mali server u EU + (pod)domena, npr. `wa.proprio.hr` | npr. Hetzner Cloud, DNS kod registrara | informatičar |

### 2.1 Prebacivanje broja na Meta Cloud API
Postojeći broj klinike prelazi s aplikacije WhatsApp Business na API. **Nakon toga se na tom broju
više ne koristi aplikacija na mobitelu** – sve poruke pacijenata recepcija čita i odgovara na
stranici `/status` (poglavlje 7).

1. **developers.facebook.com → My Apps → Create App** (tip *Business*), povežite je s Business
   portfoliom tvrtke i dodajte proizvod **WhatsApp**. Na testnom broju koji dobijete najprije
   isprobajte slanje – prije diranja pravog broja.
2. U aplikaciji WhatsApp Business na mobitelu napravite **sigurnosnu kopiju chatova**
   (Postavke → Chatovi → Sigurnosna kopija), zatim **Postavke → Račun → Izbriši račun**.
   Pričekajte nekoliko minuta.
3. **WhatsApp → API Setup → Add phone number**: prikazno ime *Proprio Centar* (kao na webu),
   potvrda SMS-om ili pozivom, postavite **6-znamenkasti PIN** i spremite ga.
4. Registrirajte broj na Cloud API (jednom):
   ```bash
   curl -X POST "https://graph.facebook.com/v23.0/PHONE_NUMBER_ID/register" \
     -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" \
     -d '{"messaging_product":"whatsapp","pin":"123456"}'
   ```
5. **Trajni token:** Business Settings → Users → System users → Add (uloga Admin) →
   Assign assets (aplikacija i WhatsApp račun, *Full control*) → Generate token s dozvolama
   `whatsapp_business_messaging` i `whatsapp_business_management`, rok **Never** → `WA_TOKEN`.
   Phone number ID (API Setup) → `WA_PHONE_NUMBER_ID`; App secret (Settings → Basic) → `WA_APP_SECRET`.
6. **WhatsApp Manager → Billing:** dodajte karticu (podsjetnici se naplaćuju po poruci).

### 2.2 Predložak poruke
U WhatsApp Manageru (business.facebook.com → WhatsApp Manager → Predlošci):

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

### 3.1 Webhook (da poruke pacijenata stižu u servis)
1. U `.env` upišite `WA_APP_SECRET` i `WA_VERIFY_TOKEN` (dugi nasumični niz: `openssl rand -hex 16`).
   Bez njih se servis ne pokreće.
2. **App Dashboard → WhatsApp → Configuration → Webhook:** Callback URL
   `https://wa.proprio.hr/whatsapp/webhook`, Verify token isti kao `WA_VERIFY_TOKEN` → *Verify and save*.
3. Pod *Webhook fields* pretplatite **messages**.
4. Pretplatite aplikaciju na WhatsApp račun (jednom; WABA ID je na stranici API Setup):
   ```bash
   curl -X POST "https://graph.facebook.com/v23.0/WABA_ID/subscribed_apps" -H "Authorization: Bearer TOKEN"
   ```
5. Aplikaciju prebacite u **Live** (App Dashboard; traži poveznicu na politiku privatnosti).

Servis provjerava Metin potpis svakog poziva (App Secret), pa lažni pozivi ne prolaze.

---

## 4. Postavke (`.env`)

Sve je opisano u `.env.example`. Najvažnije:

| Varijabla | Značenje |
|-----------|----------|
| `CLINIKO_API_KEY` | API ključ iz Clinikoa |
| `CLINIKO_USER_AGENT` | Naziv + **ispravan e-mail**, npr. `Proprio WhatsApp podsjetnici (info@proprio.hr)` – Cliniko inače blokira |
| `CLINIKO_INCLUDE_GROUP` | `true` = i grupni programi |
| `CLINIKO_WRITE_NOTES` | `true` = potvrda pacijenta upisuje se u napomenu termina |
| `WA_TOKEN`, `WA_PHONE_NUMBER_ID` | trajni System User token i ID broja (poglavlje 2.1) |
| `WA_APP_SECRET`, `WA_VERIFY_TOKEN` | provjera webhooka (poglavlje 3.1) |
| `WA_TEMPLATE_NAME` / `WA_TEMPLATE_LANG` | točno kao u odobrenom predlošku |
| `CONSENT_MODE` | `allowlist` (pilot), `custom_field` (rad), `all` |
| `REMINDER_HOURS` | sati slanja, zadano `10-19` |
| `REMINDER_DAYS_AHEAD` | `1` = podsjetnik dan prije |
| `RECEPTION_PASSWORD` | lozinka za stranicu recepcije (korisničko ime `recepcija`) |
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
- Poruke pacijenata spremaju se za inbox recepcije i brišu se, kao i ostali zapisi, nakon
  `RETENTION_DAYS` (zadano 90 dana). Stranica je zaštićena lozinkom i dostupna samo preko HTTPS-a.
- U odgovorima pacijentima nikad ne pišite dijagnozu, nalaz ni terapiju.
- U logovima su brojevi djelomično skriveni (`38598***4567`).
- Dopunite politiku privatnosti i evidenciju obrade (Meta kao izvršitelj obrade, prijenos podataka izvan EU).

---

## 6. Puštanje u rad – preporučeni redoslijed

1. U Clinikou napravite **testnog pacijenta** sa svojim mobitelom i zakažite mu lažni termin za sutra.
   `CONSENT_MODE=allowlist`, u `consent.txt` samo njegov broj → `npm run preview`, pa `npm run send`.
   Provjerite tekst, datum, sat i gumbe; kliknite gumb i pogledajte `/status`. Termin zatim otkažite.
   Pošaljite i običnu poruku na broj klinike i odgovorite na nju sa stranice `/status`.
2. U `consent.txt` dodajte 10–20 pacijenata (djelatnici, stalni pacijenti) → 1–2 tjedna.
3. Dodajte polje privole u Cliniko, `CONSENT_MODE=custom_field`.
4. U Clinikou isključite SMS podsjetnike za pacijente koji dobivaju WhatsApp (ili ih ostavite kao rezervu).

Nakon svake promjene `.env`: `sudo systemctl restart proprio-whatsapp`.

---

## 7. Svakodnevno korištenje

- **Recepcija:** `https://wa.proprio.hr/status` – preglednik traži korisničko ime `recepcija` i lozinku
  (`RECEPTION_PASSWORD`). Držite stranicu otvorenu na računalu recepcije: osvježava se svaku minutu,
  a broj neodgovorenih poruka piše u naslovu kartice. **Obavijesti na mobitelu više nema** – broj nije
  u aplikaciji.
  - **Poruke pacijenata:** svaki razgovor s imenom (iz Clinika ili WhatsApp profila) i brojem za poziv.
    *Pošalji* odgovara pacijentu i zatvara razgovor; *Riješeno* ga zatvara bez odgovora. Kad pacijent
    opet napiše, razgovor se sam ponovno otvori. Nakon 24 h od zadnje poruke pacijenta WhatsApp ne
    dopušta slobodan odgovor – tada pacijenta nazovite.
  - **Podsjetnici:** danas, sutra i prekosutra. **Označeni redovi** = nazvati pacijenta
    (nema mobitela, nema privole, poruka nije isporučena ili pacijent traži promjenu).
- **Ručno slanje / provjera (na serveru):**
  ```bash
  npm run preview -- --date=2026-10-01    # što bi se poslalo za taj dan
  npm run send -- --date=2026-10-01       # pošalji (preskače već poslane)
  npm run status -- --date=2026-10-01     # tablica zapisa
  ```
- **Zdravlje servisa:** `https://wa.proprio.hr/health`. Vraća 200 kad je sve u redu, a 503 s opisom problema ako zadnji krug slanja nije uspio (Cliniko, WhatsApp token, predložak, ispad) ili je slanje zapelo. Dodajte ga u besplatni uptime monitor (npr. UptimeRobot) s obavijesti na e-mail.

---

## 8. Najčešći problemi

| Simptom | Uzrok | Rješenje |
|---------|-------|----------|
| `Cliniko API 401` | krivi ili opozvan API ključ | novi ključ u Clinikou |
| `Cliniko API 403` / blokada | User-Agent bez e-maila | ispraviti `CLINIKO_USER_AGENT` |
| `WhatsApp 132001` | predložak ne postoji / nije odobren / kriv jezik | provjeriti naziv i `hr` u WhatsApp Manageru |
| `WhatsApp 132000` | broj varijabli ne odgovara | predložak mora imati točno {{1}} {{2}} {{3}} |
| `WhatsApp 131026` | broj nema WhatsApp | recepcija nazove; ispraviti broj u Clinikou |
| `WhatsApp 131047` | slobodna poruka više od 24 h nakon zadnje poruke pacijenta | stranica to ne dopušta; nazovite pacijenta |
| `WhatsApp 131049/131048` | Meta ograničila poruke / pacijenti blokiraju | provjeriti privole i tekst |
| `WhatsApp 190` | token istekao ili opozvan | novi System User token (poglavlje 2.1, korak 5) |
| Mnogo "nema mobitela" | broj upisan kao fiksni ili neispravno | ispraviti broj u Clinikou (tip "Mobile") |
| Odgovori se ne bilježe | webhook nije prijavljen ili kriva putanja | ponoviti korak 3.1, `journalctl -u proprio-whatsapp -f` |

**Ponovni pokušaji:**
- Greške koje **nisu do pacijenta** ne troše njegove pokušaje. To su neispravan token, nepostojeći ili pauziran predložak, plaćanje, limiti i ispad servisa. Podsjetnik se sam pošalje u sljedećem krugu (svaki sat) čim se uzrok ukloni, a `/health` do tada javlja grešku.
- Greške **vezane uz pacijenta** (npr. 131026 – broj nema WhatsApp) pokušavaju se najviše 3 puta. Ako recepcija ispravi broj u Clinikou, pokušava se ponovno na novi broj.

Detaljan katalog grešaka: `whatsapp_business_integracija_klinika.txt` (poglavlje 6).

---

## 9. Struktura koda

```
src/
  server.js     HTTP server (webhook, /status s prijavom, /health) + raspored slanja
  cli.js        naredbe: check, reminders, status
  reminders.js  dohvat termina, odabir pacijenata, slanje
  cliniko.js    Cliniko API klijent (paginacija, 429 limit, User-Agent)
  whatsapp.js   slanje predloška/teksta izravno preko Meta Cloud API-ja, ponavljanje kod privremenih grešaka
  webhook.js    provjera potpisa, statusi isporuke, odgovori pacijenata
  consent.js    privola (allowlist / Cliniko polje)
  phone.js      normalizacija hrvatskih brojeva, prepoznavanje mobitela
  time.js       vremenska zona Europe/Zagreb, promjena sata, hrvatski datumi
  db.js         SQLite baza (ugrađena u Node.js)
  status.js     stranica za recepciju (inbox poruka + pregled podsjetnika)
test/           automatski testovi (npm test) s lažnim Cliniko i WhatsApp serverom
deploy/         systemd servis i Caddy (HTTPS)
```
