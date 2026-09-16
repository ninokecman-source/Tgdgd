# Postavljanje Poprija na vanjski server — korak po korak

Vodič pretpostavlja **Ubuntu 24.04 LTS** i da na serveru ne radi ništa drugo.
Od nule do skripte koja radi treba oko 30 minuta.

Skripta ne otvara nijedan port prema van — samo se spaja na Cliniko, Solo i
mail server. Zato serveru ne treba ni domena ni certifikat ni web server.

---

## 0. Što ti treba prije početka

- novi Cliniko API ključ (stari, ako je negdje procurio, poništi)
- novi Solo API token
- SMTP podaci za mail (host, port, korisnik, app-specific lozinka)
- ID stavke "R1 - račun" iz Clinika — već je upisan u `config.example.json`
- SSH ključ na svom računalu (`ssh-keygen -t ed25519` ako ga nemaš)

---

## 1. Zakup servera

Najmanji tarifni paket je više nego dovoljan: skripta troši par MB RAM-a i
gotovo ništa procesora. Ne plaćaj ništa veće.

Pri kreiranju odaberi:

| stavka | vrijednost |
|---|---|
| lokacija | unutar EU (zbog podataka pacijenata) |
| image | Ubuntu 24.04 LTS |
| tip | najmanji dostupni (1–2 vCPU, 1–4 GB RAM) |
| SSH ključ | dodaj svoj javni ključ |
| backup | uključi ako ga provider nudi |

Zapiši IP adresu servera.

---

## 2. Prvo spajanje i osnovno osiguranje

```bash
ssh root@IP_ADRESA_SERVERA
```

```bash
# sve zakrpe
apt update && apt upgrade -y

# vremenska zona (zbog čitljivosti logova)
timedatectl set-timezone Europe/Zagreb

# vatrozid: samo SSH prema unutra, sve ostalo zatvoreno
apt install -y ufw
ufw allow OpenSSH
ufw --force enable

# automatske sigurnosne zakrpe, da server ne ostane nezakrpan
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades   # odaberi "Yes"
```

Provjeri da je prijava lozinkom isključena (ako si server kreirao sa SSH
ključem, obično već jest):

```bash
grep -E "^PasswordAuthentication|^PermitRootLogin" /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf
```

Ako igdje piše `PasswordAuthentication yes`, promijeni u `no` i
`systemctl restart ssh`.

---

## 3. Python i alati

```bash
apt install -y python3 python3-venv sqlite3 rsync
```

---

## 4. Prijenos koda

**Sa svog računala** (ne sa servera), iz foldera u kojem je `poprio/`:

```bash
rsync -av --exclude 'config.json' --exclude '__pycache__' \
      poprio/ root@IP_ADRESA_SERVERA:/opt/poprio/
```

Ako radije povlačiš iz gita, na serveru:

```bash
git clone -b Poprio https://github.com/ninokecman-source/Tgdgd.git /tmp/tgdgd
mkdir -p /opt/poprio && cp -r /tmp/tgdgd/poprio/. /opt/poprio/ && rm -rf /tmp/tgdgd
```

---

## 5. Python okruženje

```bash
cd /opt/poprio
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Zasebno okruženje, a ne `pip install` po sustavu: Ubuntu 24.04 sistemski pip
i odbija (`externally-managed-environment`), a i inače ne želiš da nadogradnja
sustava promijeni verziju knjižnice pod skriptom.

---

## 6. Korisnik servisa

Skripta ne treba root ovlasti — ako je ikad netko zloupotrijebi, neka može
što manje.

```bash
useradd --system --home /opt/poprio --shell /usr/sbin/nologin poprio
chown -R poprio:poprio /opt/poprio
```

---

## 7. config.json

```bash
cd /opt/poprio
cp config.example.json config.json
nano config.json
```

Popuni:

- `cliniko_api_key` — novi ključ, sa shard nastavkom (npr. `-au1`)
- `cliniko_user_agent` — naziv i tvoj mail, npr.
  `Poprio Cliniko-Solo integracija (nino.kecman@propriocentar.com)`
- `solo_api_token` — novi token
- `solo_tip_usluge` — ID iz Sola (Usluge → Tipovi usluga)
- `alert_email` — mail na koji stižu obavijesti o problemima
- `healthcheck_url` — vidi korak 11
- `smtp_*` — podaci za slanje maila (app-specific lozinka, ne obična)
- **`solo_document_type`: `"ponuda"`** za prvi tjedan (vidi korak 12)

Ostalo (ID-evi oznaka plaćanja, R1 stavka, nulta stopa) je već ispravno
popunjeno.

Zatim zaključaj datoteku — u njoj su ključevi koji otvaraju zdravstvene
podatke pacijenata:

```bash
chown poprio:poprio config.json
chmod 600 config.json
```

---

## 8. Provjera prije pokretanja

```bash
sudo -u poprio /opt/poprio/venv/bin/python /opt/poprio/sync.py --list-billable-items
```

Ako ispiše katalog usluga s ID-evima, Cliniko ključ radi i oznake se vide.
Ako javi grešku, config nije dobro popunjen — riješi to sada, prije nego išta
krene prema Solu.

---

## 9. Systemd servis

```bash
cp /opt/poprio/poprio.service /etc/systemd/system/poprio.service
systemctl daemon-reload

# folder za bazu obrađenih računa
install -d -o poprio -g poprio -m 700 /var/lib/poprio
```

`StateDirectory=poprio` u servisu doduše sam kreira `/var/lib/poprio`, ali tek
kad se servis **pokrene** — a inicijalizacija ide prije toga i korisnik
`poprio` sam ne smije pisati u `/var/lib`. Zato se folder kreira ručno; kasnije
ga systemd samo preuzme.

Jednokratna inicijalizacija — određuje od kojeg trenutka skripta gleda račune.
**Bez nje se servis neće pokrenuti**, namjerno: da nikad ne krene tiho s
praznom bazom i ne preskoči račune.

```bash
sudo -u poprio /opt/poprio/venv/bin/python /opt/poprio/sync.py --init-from-now
```

`--init-from-now` znači "kreni od sada" — stariji plaćeni računi se ne diraju.
To je ono što želiš; `--backfill-days N` bi obradio i račune zadnjih N dana,
a među njima ima starih bez oznake plaćanja.

```bash
systemctl enable --now poprio
systemctl status poprio
journalctl -u poprio -f
```

U logu na početku mora pisati na što se veže svaka oznaka:

```
oznaka kartice: 'Kartično plaćanje' (0.00 EUR)
oznaka gotovina: 'Gotovinsko plaćanje' (0.00 EUR)
oznaka transakcijski: 'Transkacijsko plaćanje' (0.00 EUR)
oznaka R1: R1 - račun: 'R1 - račun' (0.00 EUR)
```

Ako neka nedostaje, ID u configu je kriv — ispravi ga prije prvog pravog
računa.

---

## 10. Sigurnosna kopija baze

U `/var/lib/poprio/state.sqlite3` piše koji su računi već poslani. Ako ta
datoteka nestane, skripta ne zna što je obrađeno — a ponovno slanje istog
računa znači dupli fiskalizirani račun.

```bash
mkdir -p /var/backups/poprio
cat > /etc/cron.daily/poprio-backup <<'EOF'
#!/bin/sh
sqlite3 /var/lib/poprio/state.sqlite3 \
  ".backup /var/backups/poprio/state-$(date +%A).sqlite3"
EOF
chmod +x /etc/cron.daily/poprio-backup
```

Ovo drži sedam kopija (jednu po danu u tjednu). `.backup` radi ispravnu kopiju
i dok skripta piše — obično `cp` u tom trenutku može uhvatiti pola upisa.

---

## 11. Vanjski nadzor (healthchecks.io)

Ovo je jedino što može javiti da je **sam server** stao. Mrtav proces ne može
poslati mail o sebi.

1. Otvori besplatan račun na <https://healthchecks.io>
2. New Check → naziv "Poprio", **Period 1 hour**, **Grace 30 minutes**
3. Kopiraj ping URL u `healthcheck_url` u `config.json`
4. `systemctl restart poprio`
5. U healthchecks.io provjeri da check unutar minute postane zelen

Dodaj i svoj mail pod Notifications da ti stigne obavijest kad prestane
javljati.

---

## 12. Probni rad

**Prvi tjedan ostavi `"solo_document_type": "ponuda"`.** Sve radi identično,
ali u Solu nastaju ponude umjesto fiskalnih računa — pa ako nešto nije kako
treba, briše se bez storna.

Provjeri na prvih nekoliko:

- iznos ponude = iznos računa u Clinku
- stavke su iste kao u Clinku (oznake od 0 EUR se ne prenose)
- način plaćanja odgovara oznaci na računu
- račun na tvrtku (s "R1 - račun") završi kao ponuda i stigne mail

Kad prođe tjedan bez iznenađenja:

```bash
nano /opt/poprio/config.json     # "solo_document_type": "racun"
systemctl restart poprio
```

Prvi pravi račun provjeri u Solu: JIR i ZKI moraju postojati, iznos i stavke
se moraju poklapati.

---

## Svakodnevno održavanje

Ništa. Servis se sam diže nakon reboota i restarta nakon pada.

| situacija | što se dogodi |
|---|---|
| račun bez oznake plaćanja | ne fiskalizira se, stiže mail, čeka ispravak u Clinku |
| Solo ili Cliniko privremeno nedostupan | ponavlja sam, nakon 5 pokušaja mail |
| server se ugasi | healthchecks.io javlja mailom |
| oznaka obrisana u Clinku | mail pri pokretanju |

## Nadogradnja koda

```bash
# sa svog računala
rsync -av --exclude 'config.json' --exclude '__pycache__' \
      poprio/ root@IP_ADRESA_SERVERA:/opt/poprio/

# na serveru
chown -R poprio:poprio /opt/poprio
systemctl restart poprio
```

`config.json` i baza u `/var/lib/poprio/` se ne diraju — zato baza i **ne
smije** živjeti u `/opt/poprio`.

## Korisne naredbe

```bash
systemctl status poprio          # radi li
journalctl -u poprio -f          # log uživo
journalctl -u poprio --since today
systemctl restart poprio         # nakon izmjene configa

# što je u bazi
sqlite3 /var/lib/poprio/state.sqlite3 \
  "SELECT status, COUNT(*) FROM processed_invoices GROUP BY status;"

# računi koji čekaju ispravak
sqlite3 /var/lib/poprio/state.sqlite3 \
  "SELECT cliniko_number, last_error FROM processed_invoices WHERE status='waiting';"
```
