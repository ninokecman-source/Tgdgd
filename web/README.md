# Web pregled

Stranica za mobitel s kojom se vidi što sustav radi: tečajevi i prijavljeni,
kome manjka uplata, što je zadnje poslano, proknjižene uplate i greške iz
logova. **Samo za čitanje** — ništa ne pokreće i ništa ne mijenja.

Stoji na istom serveru kao i Cliniko, ali **nije na internetu**: objavljuje
je Tailscale, privatna mreža u koju su spojeni samo server i tvoji uređaji.
Nitko izvana ne može ni pokucati na nju. Cliniko ostaje netaknut.

```
                HTTPS, samo                  127.0.0.1:8099
                 unutar mreže
   iPhone  ────────────────────►  Tailscale  ──────────────►  gunicorn
   (Tailscale                      serve                         │
    uključen)                       :443                  web/stanje.json
                                                                 ▲
                              cron, svakih 20 min: osvjezi.sh ───┘
                              (rclone iz Dropboxa + web/skupi.py)
```

Serve sluša na 443, ali **samo na Tailscale adresi** — na javnoj adresi
servera ne otvara ništa. Prije postavljanja ipak provjeri da taj port nije
već nečiji (`ss -tlnp | grep -E ':(80|443)\s'`): ako na serveru postoji web
poslužitelj koji sluša na `0.0.0.0:443`, to obuhvaća i Tailscale adresu, pa
bi se potukli — a nakon ponovnog pokretanja servera onaj drugi mogao bi
ostati bez porta. U tom slučaju uzmi 8443
(`tailscale serve --bg --https=8443 8099`); adresa tada nosi i port.

Stranica **ne čita Excel tablice**. Čita snimku koju svakih dvadeset minuta
napravi `web/skupi.py`, pod istom bravom kao i ostali poslovi. Dva razloga:
tablice se ne diraju dok u njih netko piše, a petnaest Excel datoteka se ne
otvara pri svakom osvježavanju stranice na mobitelu. Ako snimka zastari,
stranica to javi na vrhu — i to je ujedno najbrža provjera radi li cron.

## Postavljanje

Sve kao `emmett`, osim koraka koji izričito traže `root`.

### 1. Paketi

```bash
~/venv/bin/pip install -r ~/Tgdgd/web/requirements.txt
```

### 2. Lozinka

```bash
~/venv/bin/python ~/Tgdgd/web/postavi_lozinku.py
```

Traži korisničko ime i lozinku (najmanje 10 znakova). U `config.json` se
upisuje samo scrypt hash, nikad sama lozinka, plus `web_secret_key` kojim
Flask potpisuje kolačić prijave.

### 3. Prva snimka

```bash
~/Tgdgd/server/pokreni.sh web/skupi.py
```

Mora ispisati koliko je tečajeva našao.

### 4. Servis

```bash
sudo cp ~emmett/Tgdgd/web/emmett-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now emmett-web
systemctl status emmett-web
curl -I http://127.0.0.1:8099/        # mora vratiti 302 na /prijava
```

### 5. Tailscale (kao `root`)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
```

`tailscale up` ispiše poveznicu — otvori je u pregledniku i prijavi se
(Google račun je dovoljan). Time server ulazi u tvoju privatnu mrežu.

U Tailscale konzoli (`login.tailscale.com`) preimenuj uređaj iz
`ubuntu-4gb-nbg1-1` u **`emmett`**, da adresa bude kratka.

Zatim:

```bash
tailscale serve --bg 8099
tailscale serve status
```

`status` ispiše punu adresu — nešto poput `https://emmett.tail1234.ts.net`.
To je adresa stranice.

Ako si uređaj preimenovao nakon što si već pokrenuo `serve`, u popisu ostanu
dva zapisa, stari i novi. Počisti sa `tailscale serve reset`, pa ponovi.

Prvi put će Serve tražiti da se za mrežu uključe HTTPS certifikati; ponudi
poveznicu na koju klikneš i potvrdiš. Certifikat je pravi, Safari ne
prigovara.

**Provjeri što sluša:**

```bash
ss -tlnp | grep -E ':(80|443)\s'
```

Mora se vidjeti samo `tailscaled` na Tailscale adresi. Ako ondje stoji još
nešto na `0.0.0.0:443`, vrati se na 8443.

### 5b. iPhone

1. App Store → **Tailscale** → instaliraj.
2. Prijavi se **istim računom** kao na serveru.
3. Uključi prekidač (ostaje uključen, troši zanemarivo).
4. Otvori adresu iz `tailscale serve status` u Safariju.
5. Share → **Add to Home Screen** — dobiješ ikonu kao da je aplikacija.

Ako Tailscale na mobitelu isključiš, stranica se neće otvoriti. To nije
kvar, nego cijela poanta.

### 6. Tipke (slanje potvrdnica)

Kao `root`:

```bash
cp ~emmett/Tgdgd/server/emmett-zahtjev.path /etc/systemd/system/
cp ~emmett/Tgdgd/server/emmett-zahtjev.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now emmett-zahtjev.path
systemctl status emmett-zahtjev.path --no-pager | head -3
```

Provjera cijelog puta, kao `emmett`:

```bash
mkdir -p ~/zahtjevi
# pritisak na tipku "Pregled, bez slanja" ovo napravi sam
printf '{"posao":"pregled_certifikata","tablica":"Modul 1&2 Split.xlsx","trazio":"rucno"}' \
    > ~/zahtjevi/proba.json
sleep 20
cat ~/Tgdgd/web/zahtjevi.json
```

Mora se vidjeti ishod sa statusom `gotovo` i ispisom posla.

### 7. Cron

Nova linija je već u `server/crontab.txt` (zamjenjuje golu sinkronizaciju):

```bash
crontab ~/Tgdgd/server/crontab.txt
crontab -l | tail -3
```

## Svakodnevno

Dodirneš ikonu na početnom zaslonu. Prijava traje mjesec dana, pa lozinku
tražiš rijetko; promijeni to s `web_session_days` u `config.json`.

| Stranica | Što pokazuje |
|---|---|
| Tečajevi | tečajevi pred nama i prošli, broj prijavljenih, uplaćeno |
| Tečaj | polaznici, uplate, što im je poslano, tipke za potvrdnice |
| Uplate | kome manjka novac, proknjižene uplate iz banke |
| Stanje | zadnji prolazi cron poslova, greške iz logova |

### Slanje potvrdnica s mobitela

Na stranici tečaja, ispod "Što je poslano":

- **Pregled, bez slanja** — pokaže tko bi što dobio, ne šalje ništa.
- **Pošalji potvrdnice** — vodi na potvrdu s popisom primatelja; tek tamo
  drugi pritisak stvarno šalje.

Dok posao traje, stranica se osvježava sama i pokaže ispis kad završi. Tko
je potvrdnicu jednom dobio, neće je dobiti dvaput, koliko god puta
pritisnuo — to pamti `poslani_certifikati.json`, isto kao i kod naredbe iz
terminala.

**Kako radi iznutra.** Stranica sama ne šalje ništa. Tipka ostavi datoteku
sa zahtjevom u `~/zahtjevi`, systemd to primijeti (`emmett-zahtjev.path`) i
pokrene `server/izvrsi.py`, koji posao odradi kroz `pokreni.sh` — dakle pod
istom bravom i s istim pravima kao cron.

Razlog je jednostavan: web je jedini proces ovdje koji sluša izvana. Ovako
smije pisati samo u tu jednu mapu, a `izvrsi.py` prihvaća samo poslove sa
svog kratkog popisa i samo tablice koje stvarno postoje. Ni da mu netko
preotme vlast, web ne može poslati mail polazniku ni promijeniti tablicu.

## Sigurnost

Kroz stranicu idu imena, adrese, mailovi i telefoni polaznika, pa:

- **Stranica nije na internetu.** Dohvatljiva je jedino s uređaja u tvojoj
  Tailscale mreži. Tko ne uđe u mrežu, ne može ni probati lozinku.
- Gunicorn sluša samo na `127.0.0.1`.
- **Bez HTTPS-a se ne koristi.** Kolačić prijave ima `Secure`, što znači da
  preko običnog `http://` prijava neće ni raditi.
- Lozinka se čuva kao scrypt hash. Promjena: ponovno `postavi_lozinku.py`,
  pa `systemctl restart emmett-web`.
- Pet promašenih prijava znači petnaest minuta pauze.
- Stranica je označena s `noindex, nofollow` — ionako je nijedna tražilica
  ne može vidjeti.
- Systemd servisu su oduzeta prava koja mu ne trebaju: ne smije pisati po
  disku (`ProtectSystem=strict`, `ProtectHome=read-only`) ni dobiti nova
  ovlaštenja (`NoNewPrivileges`).
- Lozinka je i dalje tu iako je mreža privatna: da izgubljen, otključan
  telefon ne znači i otvorenu kartoteku polaznika.
- Tipke ne rade posao same, nego ga traže od zasebnog procesa (vidi gore).
  Obrasci nose tajnu iz prijave, pa ih tuđa stranica ne može poslati umjesto
  tebe.

## Kad nešto ne radi

| Što se vidi | Gdje gledati |
|---|---|
| "Nema snimke podataka" | `~/Tgdgd/server/pokreni.sh web/skupi.py` i pročitaj grešku |
| "Podaci su stari N min" | `crontab -l`, pa `tail ~/Tgdgd/log.txt` |
| 502 Bad Gateway | `systemctl status emmett-web`, `journalctl -u emmett-web -n 50` |
| Stranica se uopće ne otvara | je li Tailscale na mobitelu uključen? Pa `tailscale status` na serveru |
| Tipka ništa ne napravi | `systemctl status emmett-zahtjev.path`, pa `ls ~/zahtjevi` — stoji li zahtjev neodrađen |
| Prijava ne prolazi, a lozinka je dobra | ide li preko `https://`? Kolačić je `Secure`. |
| Tečaj nedostaje | "Upozorenja iz tablica" na prvoj stranici — vjerojatno kopija ili sukob sinkronizacije |

## Proba bez Tailscalea

```bash
EMMETT_WEB_HTTP=1 ~/venv/bin/python ~/Tgdgd/web/app.py
```

Sluša na `127.0.0.1:8099`, bez `Secure` kolačića. Služi samo za probu preko
SSH tunela (`ssh -L 8099:localhost:8099 emmett`), ne za pogon.

## Ako jednom zatrebaš javnu adresu

U repozitoriju stoji i `web/nginx-emmett.conf` — gotov vhost za slučaj da
dobiješ subdomenu i poželiš stranicu na internetu, s certifikatom od
`certbot --nginx`. Tada Tailscale Serve nije potreban:
`tailscale serve --https=443 off`. Dok god je ovako, taj se vhost ne
koristi.
