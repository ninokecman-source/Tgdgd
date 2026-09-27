# Proprio Centar – WhatsApp podsjetnici i inbox (Cloud API)

Samostalan projekt napravljen prema uputama
`Dropbox/Proprio/whatsup/whatsapp_business_integracija_klinika.txt`, **put C**
(izravno Meta WhatsApp Cloud API + vlastiti mali backend). Termini se čitaju iz
Clinika. Oznake G-xx u kodu i porukama odgovaraju katalogu grešaka iz uputa.

## Što radi

| Tok iz uputa | Kako |
|---|---|
| (1) Podsjetnik 24 h prije termina | `npm run podsjetnici` iz crona svakih 15 min: termini iz Clinika → samo pacijenti s privolom → predložak `podsjetnik_termin` → wamid u bazu |
| (2) Potvrda / promjena gumbom | gumb se povezuje s terminom preko `context.id`; „Potvrđujem" → potvrđeno, „Trebam promjenu" → zadatak recepciji „nazvati" |
| (3) Slobodne poruke pacijenta | idu u inbox na `/recepcija`; recepcija odgovara unutar 24 h |
| (4) Statusi isporuke | sent → delivered → read; kod `failed` zadatak recepciji s razlogom (rezervni kanal: poziv/SMS) |

Uz to:

- **STOP / ODJAVA** od pacijenta odmah opoziva privolu i potvrđuje odjavu.
- **Zaštita od duplog slanja** (G-82): atomsko zaključavanje po terminu. Ako proces padne usred slanja, podsjetnik se ne šalje ponovno, nego ide recepciji na provjeru.
- **Termin otkazan ili pomaknut** (G-81): termin se ponovno provjerava u Clinikou neposredno prije slanja. Pomaknuti termin dobije novi podsjetnik za novo vrijeme.
- **Greške** se dijele na tri vrste:
  - privremene: ponavljaju se (1 s, 2 s, 4 s, 8 s, pa u sljedećem prolazu);
  - vezane uz pacijenta: zadatak recepciji;
  - kvar postavki (npr. istekao token): posao staje, a termini ostaju na čekanju.
- **Nije isporučeno** 4 h prije termina (G-51): zadatak recepciji.
- **Webhook** (G-30 do G-35):
  - potpis se provjerava na sirovom tijelu zahtjeva;
  - događaj se spremi u bazu prije odgovora 200, pa se ništa ne gubi ako server padne;
  - duplikati se ignoriraju;
  - status se nikad ne vraća unatrag.
- **Zona Europe/Zagreb** (G-80): u bazi je UTC, a datum i sat u poruci su lokalni, i ljeti i zimi.
- **Rok čuvanja** (poglavlje 5): poruke i podsjetnici se brišu nakon 365 dana, a sirovi webhook događaji nakon 7 dana.
- **Nadzor**:
  - `/zdravlje` vraća 503 ako cron ne radi ili webhook ne javlja statuse;
  - dnevni izvještaj „poslano X".
- **Dijagnostika**: `npm run alat -- provjera` i `npm run alat -- greska <kod>`.

### Što namjerno NE radi

- **Ne piše u Cliniko.** Potvrde se vide na `/recepcija`.
- **Ne šalje zdravstvene podatke.** Predložak ima samo ime, datum i sat.
- **Ne preuzima slike ni glasovne poruke.** Recepcija dobije napomenu da je pacijent poslao medij.
- **Ne radi s WhatsApp Business aplikacijom na mobitelu** ni s neslužbenim alatima.
- **Pazi na dvostruke podsjetnike:** ako Cliniko već šalje SMS podsjetnike, pacijent s WhatsApp privolom dobit će oboje. Za njih isključite SMS podsjetnik u Clinikou.

## Što treba prije (poglavlje 1)

- Verificiran Meta Business portfolio, WhatsApp broj klinike i odobreno prikazno ime.
- **Server koji je stalno upaljen** (VPS u EU), ne osobno računalo. Meta webhook mora biti dostupan 0–24.
- Domena s HTTPS-om, npr. `api.proprio.hr`. Caddy sam nabavi certifikat (`deploy/Caddyfile`).
- Node.js 20.12 ili noviji.
- Cliniko API ključ.

## Instalacija

```bash
git clone -b claude/whatsapp-proprio https://github.com/ninokecman-source/Tgdgd /opt/proprio-whatsapp
cd /opt/proprio-whatsapp
npm ci --omit=dev
cp .env.example .env      # pa popuni – svako polje je objašnjeno u datoteci
```

## Postavljanje, korak po korak (poglavlje 2 uputa)

1. **Korak 1–2**: Business portfolio, verifikacija i Developer aplikacija. To se radi ručno u Meta sučelju, prema uputama.
2. **Korak 3**: dodaj broj, verificiraj ga i postavi 6-znamenkasti PIN (spremi ga u upravitelj lozinki). Zatim:
   ```bash
   npm run alat -- registriraj 123456
   ```
3. **Korak 4**: System User token upiši u `WA_TOKEN`. U `.env` upiši i `WA_PHONE_NUMBER_ID`, `WA_WABA_ID` i `WA_APP_SECRET`.
4. **Korak 5 – webhook**:
   - pokreni server (vidi „Pokretanje") i Caddy;
   - u App Dashboardu → WhatsApp → Configuration upiši Callback URL `https://api.proprio.hr/whatsapp/webhook` i isti `WA_VERIFY_TOKEN`;
   - pretplati se na polja `messages` i `message_template_status_update`;
   - pokreni:
     ```bash
     npm run alat -- pretplati
     ```
   - aplikaciju prebaci u **Live**.
5. **Korak 6 – predložak** u WhatsApp Manageru. Kategorija **UTILITY**, jezik **hr**, naziv `podsjetnik_termin`:
   ```
   Poštovani/a {{1}}, podsjećamo Vas na termin u Proprio Centru
   {{2}} u {{3}} h. Molimo potvrdite dolazak.
   [Quick reply: Potvrđujem]  [Quick reply: Trebam promjenu]
   ```
   Primjeri varijabli za predaju: `Ana Horvat`, `30.9.2026.`, `14:30`. Ako promijeniš tekst gumba, promijeni i `WA_BUTTON_CONFIRM` / `WA_BUTTON_CHANGE`.
6. **Korak 7 – test**:
   ```bash
   npm run alat -- provjera                 # sve redom: token, broj, pretplata, predložak, Cliniko, webhook
   npm run alat -- test-poruka 0981234567   # predložak na tvoj mobitel
   npm run podsjetnici -- --probno          # što bi sutra poslao, bez slanja
   ```
7. **Korak 8 – puštanje**: upiši privole za 10–20 pacijenata (pilot) i uključi cron. Kad sve radi, upisuj privole svima koji pristanu.

## Pokretanje

- **Server** (webhook + recepcija): `npm start`. Za stalni rad koristi `deploy/proprio-whatsapp.service` (systemd, automatski restart).
- **Podsjetnici**: cron svakih 15 minuta, vidi `deploy/crontab.txt`. Posao sam pazi na sate slanja (`SEND_HOURS`, zadano 8–20 h po zagrebačkom vremenu), pa vrijeme u cronu nije bitno.

Server sluša samo na `127.0.0.1`, a van ga izlaže Caddy s HTTPS-om.

## Privole (poglavlje 5)

Poruke dobivaju **samo** pacijenti s evidentiranom privolom. Za svaku se pamti
kada je dana, kako i za koji broj. Privolu upisuješ na jedan od tri načina:

- na stranici `/recepcija` (obrazac „Upiši privolu");
- iz naredbenog retka:
  ```bash
  npm run alat -- privola-dodaj 0981234567 "obrazac pri naručivanju"
  ```
- skupno iz CSV-a (npr. izvoz iz Excela):
  ```bash
  npm run alat -- privola-uvoz privole.csv
  ```
  Stupci su `telefon;izvor;datum;cliniko_id`; zadnja dva nisu obavezna.

Broj se upisuje kako god je zapisan (`098 123 4567`, `+385…`, `00385…`) i sam se
normalizira. Opoziv: gumb na stranici, `privola-opozovi <broj>` ili poruka **STOP**
od pacijenta.

## Stranica za recepciju – `/recepcija`

Zaštićena korisničkim imenom i lozinkom (`RECEPTION_USER` / `RECEPTION_PASSWORD`). Prikazuje:

- **Zadatke**: traži promjenu, nije isporučeno, poruka pacijenta, odjava… Broj je poveznica za poziv. Na poruku pacijenta može se odgovoriti tekstom dok ne prođe 24 h (G-40); nakon toga stranica traži da se pacijenta nazove.
- **Termine sljedeća 2 dana**, sa stanjem podsjetnika (poslano / isporučeno / pročitano / NIJE isporučeno) i odgovorom pacijenta.
- **Privole**: upis, opoziv i popis.

U odgovore nikad ne pišite dijagnozu, nalaz ni terapiju (G-91).

## Nadzor (G-87)

- `https://api.proprio.hr/zdravlje` vraća 200 kad je sve u redu, a 503 s popisom problema kad nije. Uključi besplatni uptime monitor (npr. UptimeRobot) na tu adresu s obavijesti e-mailom/SMS-om. Javlja:
  - da se cron nije pokrenuo zadnjih sat vremena;
  - da je zadnji prolaz prekinut (npr. istekao token);
  - da su poruke poslane, a webhook nije javio ni jedan status.
- **Dnevni izvještaj**: `npm run alat -- izvjestaj [GGGG-MM-DD]` ispisuje:
  - koliko je podsjetnika poslano, isporučeno, pročitano i neuspjelo;
  - koliko je pacijenata potvrdilo dolazak ili traži promjenu;
  - koliko je stiglo poruka od pacijenata.

## Kad nešto ne radi (poglavlje 7)

```bash
npm run alat -- provjera          # provjeri sve postavke redom
npm run alat -- greska 131047     # što znači kod i kako ga ispraviti
```

U logu (`data/podsjetnici.log`, `journalctl -u proprio-whatsapp`) greške imaju
oznaku `[GREŠKA]`, a upozorenja `[!]`. Svaka greška iz Mete ispisuje se s oznakom
iz uputa, npr. `G-20 (190) Pristupni token je istekao… Ispravak: …`. Logovi ne
sadrže tekst poruka, a brojevi su skraćeni (`385981***67`).

| Vrsta greške | Primjeri | Što sustav radi |
|---|---|---|
| Privremena | 131000, 130429, 131056, mreža | ponavlja odmah (1–8 s), pa u sljedećim prolazima (`MAX_SEND_ATTEMPTS`), zatim zadatak recepciji |
| Vezana uz pacijenta | 131026 (nema WhatsApp), 131030, 131049 | ne ponavlja; zadatak recepciji „nazvati ili SMS" |
| Kvar postavki / računa | 190 (token), 132001 (predložak), 131042 (plaćanje), 80007 | zaustavlja slanje, termini čekaju popravak, `/zdravlje` javlja 503 |

## Kontrolna lista prije puštanja (poglavlje 8)

- [ ] Tvrtka verificirana, 2+ admina s 2FA *(Meta)*
- [ ] Prikazno ime odobreno, profil popunjen *(Meta; `provjera` javlja stanje imena)*
- [ ] Broj registriran, PIN spremljen *(`alat registriraj`; `provjera`)*
- [ ] System User token samo u `.env` na serveru *(`.env` je u `.gitignore`)*
- [ ] Webhook: HTTPS, potpis, brzi 200, red, idempotentnost *(ugrađeno; `provjera` testira URL)*
- [ ] Predložak UTILITY, jezik „hr", 3 varijable, 2 gumba *(`provjera`)*
- [ ] Normalizacija brojeva i čišćenje varijabli *(ugrađeno)*
- [ ] Zona Europe/Zagreb *(ugrađeno, testirano oko promjene sata)*
- [ ] Zaštita od duplog slanja *(ugrađeno)*
- [ ] Rezervni kanal kod „failed" *(zadatak recepciji s brojem za poziv)*
- [ ] Privole evidentirane, STOP radi
- [ ] Politika privatnosti i evidencija obrade ažurirane *(pravno – nije u kodu)*
- [ ] Uptime monitor na `/zdravlje`, dnevni izvještaj u cronu
- [ ] Pilot s 10–20 pacijenata

## Razvoj

```bash
npm install
npm test
```

| Datoteka | Sadržaj |
|---|---|
| `src/server.js` | webhook, `/zdravlje`, pokretanje servera |
| `src/webhook.js` | obrada događaja (gumbi, poruke, STOP, statusi) |
| `src/reminders.js` | posao podsjetnika |
| `src/reception.js` | stranica za recepciju |
| `src/cli.js` | alat za postavljanje i dijagnostiku |
| `src/whatsapp.js` | Cloud API klijent |
| `src/cliniko.js` | Cliniko API klijent |
| `src/errors.js` | katalog grešaka G-xx |
| `src/db.js` | SQLite baza |
| `src/phone.js`, `src/timeutil.js` | brojevi i vrijeme |
