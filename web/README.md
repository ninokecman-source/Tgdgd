# Web pregled

Stranica za mobitel s kojom se vidi što sustav radi: tečajevi i prijavljeni,
kome manjka uplata, što je zadnje poslano, proknjižene uplate i greške iz
logova. **Samo za čitanje** — ništa ne pokreće i ništa ne mijenja.

Stoji na istom serveru kao i Cliniko, kao zaseban nginx vhost. Cliniko
ostaje netaknut.

```
                 HTTPS                      127.0.0.1:8099
   iPhone  ────────────────►  nginx  ───────────────────────►  gunicorn
                                                                  │
                                                           web/stanje.json
                                                                  ▲
                               cron, svakih 20 min: osvjezi.sh ────┘
                               (rclone iz Dropboxa + web/skupi.py)
```

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

### 5. Adresa i nginx

Prvo DNS: A zapis za subdomenu (npr. `emmett.emmett-hr.com`) na IP servera.
Provjeri da je prošao (`dig +short emmett.emmett-hr.com`) prije certbota —
inače Let's Encrypt ne može potvrditi domenu.

```bash
sudo cp ~emmett/Tgdgd/web/nginx-emmett.conf /etc/nginx/sites-available/emmett
sudo nano /etc/nginx/sites-available/emmett     # upiši svoju adresu
sudo ln -s /etc/nginx/sites-available/emmett /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d emmett.emmett-hr.com
```

`certbot` sam dopiše HTTPS i preusmjeravanje s porta 80. Postojeći Cliniko
vhostovi se ne diraju — nginx ih razlikuje po `server_name`.

### 6. Cron

Nova linija je već u `server/crontab.txt` (zamjenjuje golu sinkronizaciju):

```bash
crontab ~/Tgdgd/server/crontab.txt
crontab -l | tail -3
```

## Svakodnevno

Otvori adresu na iPhoneu i spremi je na početni zaslon (Share → Add to Home
Screen). Prijava traje do zatvaranja preglednika.

| Stranica | Što pokazuje |
|---|---|
| Tečajevi | tečajevi pred nama i prošli, broj prijavljenih, uplaćeno |
| Tečaj | polaznici s adresama i uplatama, što im je poslano |
| Uplate | kome manjka novac, proknjižene uplate iz banke |
| Stanje | zadnji prolazi cron poslova, greške iz logova |

## Sigurnost

Kroz stranicu idu imena, adrese, mailovi i telefoni polaznika, pa:

- **Bez HTTPS-a se ne koristi.** Kolačić prijave ima `Secure`, što znači da
  preko običnog `http://` prijava neće ni raditi.
- Gunicorn sluša samo na `127.0.0.1` — izvana je dostupan isključivo kroz
  nginx.
- Lozinka se čuva kao scrypt hash. Promjena: ponovno `postavi_lozinku.py`,
  pa `sudo systemctl restart emmett-web`.
- Pet promašenih prijava s iste adrese znači petnaest minuta pauze.
- Stranica je označena s `noindex, nofollow`, a nginx dodaje i
  `X-Robots-Tag` — ne pojavljuje se u tražilicama.
- Systemd servisu su oduzeta prava koja mu ne trebaju: ne smije pisati po
  disku (`ProtectSystem=strict`, `ProtectHome=read-only`) ni dobiti nova
  ovlaštenja (`NoNewPrivileges`).

## Kad nešto ne radi

| Što se vidi | Gdje gledati |
|---|---|
| "Nema snimke podataka" | `~/Tgdgd/server/pokreni.sh web/skupi.py` i pročitaj grešku |
| "Podaci su stari N min" | `crontab -l`, pa `tail ~/Tgdgd/log.txt` |
| 502 Bad Gateway | `systemctl status emmett-web`, `journalctl -u emmett-web -n 50` |
| Prijava ne prolazi, a lozinka je dobra | ide li preko `https://`? Kolačić je `Secure`. |
| Tečaj nedostaje | "Upozorenja iz tablica" na prvoj stranici — vjerojatno kopija ili sukob sinkronizacije |

## Proba bez nginxa

```bash
EMMETT_WEB_HTTP=1 ~/venv/bin/python ~/Tgdgd/web/app.py
```

Sluša na `127.0.0.1:8099`, bez `Secure` kolačića. Služi samo za probu preko
SSH tunela (`ssh -L 8099:localhost:8099 emmett`), ne za pogon.
