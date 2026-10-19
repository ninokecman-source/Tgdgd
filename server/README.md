# Emmett sustav na serveru

Upute za selidbu s Maca na server, korak po korak. Radi se pod korisnikom
`emmett`, odvojeno od svega ostalog na tom serveru.

Tablice žive u Dropboxu: Mac ih sinkronizira Dropbox aplikacijom, server
preko `rclone`. Ti i dalje uređuješ tablice u Excelu kao i dosad.

---

## 1. Priprema servera (kao `root`)

```bash
adduser --disabled-password --gecos "" emmett
apt update
apt install -y python3-venv chromium fonts-liberation
```

rclone iz `apt` je prestar (1.60) — bisync je ondje još bio nedozreo, a
zastavice za rukovanje sukobima došle su tek u 1.66. Instaliraj službeni:

```bash
curl -fsSL https://rclone.org/install.sh | bash
rclone version
```

Mora pisati 1.66 ili više.

`fonts-liberation` nije sitnica: potvrdnice koriste Arial, a Liberation Sans
mu je metrički istovjetan. Bez njega bi se razmaci na potvrdnici razišli.

Na Ubuntu 26.04 `chromium` se instalira kao **snap**, a `apt` postavi
`/usr/bin/chromium-browser` kao put do njega. To je u redu — skripta za
potvrdnice privremenu datoteku piše uz sam PDF, ne u `/tmp`, baš zato što
snap ima vlastiti `/tmp` i onaj pravi ne vidi.

## 2. Kod i Python (kao `emmett`)

```bash
su - emmett
git clone -b server https://github.com/ninokecman-source/Tgdgd.git ~/Tgdgd
python3 -m venv ~/venv
~/venv/bin/pip install openpyxl requests
```

Na serveru je **jedan** klon, ne dva — `bank_solo` je u istom repozitoriju.

## 3. Dropbox

```bash
rclone config
```

Odaberi `n` (new remote), naziv **`dropbox`**, tip `dropbox`, ostalo Enter.
Na pitanje o autorizaciji odaberi **`n`** (nije automatski) — dobit ćeš
naredbu koju pokreneš na svom Macu, pa vratiš ispisani token na server.

Provjera i prvo povlačenje:

```bash
rclone lsd dropbox:Prijave
~/Tgdgd/server/sinkroniziraj.sh --resync
ls ~/Prijave
```

`--resync` ide **samo prvi put** — tada rclone upamti polazno stanje.
Poslije se pokreće bez njega. U `~/Prijave` moraš vidjeti tablice,
`Lokacija Split.docx` i oba predloška potvrdnica.

## 4. Postavke

Dvije datoteke s lozinkama. **Upiši ih izravno na serveru**, ne šalji ih
nikome.

```bash
cd ~/Tgdgd
cp config.example.json config.json
cp bank_solo/config.example.json bank_solo/config.json
chmod 600 config.json bank_solo/config.json
nano config.json
```

U `config.json` promijeni:

| Ključ | Vrijednost na serveru |
|---|---|
| `zoho_app_password` | nova app-lozinka iz Zoha |
| `output_dir` | `/home/emmett/Prijave` |
| `chrome_path` | `/usr/bin/chromium` (ili što je ispalo u 1. koraku) |
| `watch_logs` | `{"prijave i podsjetnici": "/home/emmett/Tgdgd/log.txt", "izvodi i Solo": "/home/emmett/Tgdgd/sync.log"}` |

Ostalo (tekstovi poruka, podsjetnici, cijene, prekidači) prepiši iz
`config.json` sa svog Maca — to su tvoje postavke, ne diraj ih.

U `bank_solo/config.json`: `zoho_app_password`, `solo_api_token`,
`excel_dir` na `/home/emmett/Prijave`, `state_db_path` na
`/home/emmett/Tgdgd/bank_solo/bank_solo_state.sqlite3`.

## 5. Prenesi evidenciju s Maca — NE PRESKAČI

Skripte pamte što su već napravile. Ako te datoteke ne prenesеš, server
kreće od nule: **svi polaznici dobiju potvrde i podsjetnike ponovno, a u
Solu nastanu duple ponude.**

Na Macu:

```bash
cd /Users/ninokecman/Tgdgd
scp processed_uids.json sent_reminders.json sent_reports.json \
    log_check_state.json napravljeni_certifikati.json \
    poslani_certifikati.json emmett@<IP-SERVERA>:~/Tgdgd/
scp /Users/ninokecman/Tgdgd-bank-solo/bank_solo/bank_solo_state.sqlite3 \
    emmett@<IP-SERVERA>:~/Tgdgd/bank_solo/
```

Ako neka od njih ne postoji, preskoči je — nastat će sama.

Provjera na serveru:

```bash
cd ~/Tgdgd && ls -la *.json bank_solo/*.sqlite3
~/venv/bin/python3 bank_solo/diagnose.py --proknjizeno
```

Zadnja naredba mora ispisati sve dosadašnje uplate. Ako kaže da ih nema,
baza nije prenesena — **stani i riješi to prije nego išta pokreneš.**

## 6. Proba, bez slanja

```bash
cd ~/Tgdgd
server/pokreni.sh send_reminders.py --popis
server/pokreni.sh posalji_tablicu.py --pregled
server/pokreni.sh napravi_certifikate.py --pregled
```

Mora izgledati isto kao na Macu: iste tablice, isti datumi, isti brojevi
polaznika. Ako se razlikuje, Dropbox nije sve prenio.

## 7. Raspored

```bash
crontab ~/Tgdgd/server/crontab.txt
crontab -l
```

Server radi u UTC, pa crontab postavlja `TZ=Europe/Zagreb`. Bez toga bi
podsjetnici išli krivi dan.

## 8. Ugasi cron na Macu — tek kad server radi

Dok oboje rade, oboje bi slalo iste poruke. Na Macu:

```bash
crontab -l > ~/crontab-mac-prije-gasenja.txt
crontab -r
```

Prvi redak spremi kopiju, da se možeš vratiti.

---

## Kako to radi

`server/pokreni.sh <skripta>` je jedini način pokretanja. Uvijek radi isto:

1. povuče svježe tablice iz Dropboxa
2. odradi posao
3. vrati promjene u Dropbox

Sve troje pod jednom bravom (`flock`), pa se dva cron posla nikad ne
preklope ni međusobno ni sa sinkronizacijom. Ako posao padne, promjene se
svejedno vraćaju u Dropbox, a izlazni status se prenosi dalje — pa ga
uhvati provjera logova.

Svakih 20 minuta ide i sinkronizacija bez posla, da Dropbox ne zaostane
između cron termina — `server/osvjezi.sh`, koji uz sinkronizaciju osvježi i
snimku za web pregled. Ta se preskače ako brava nije slobodna.

### Sukobi

Ako Mac i server promijene istu tablicu između dvije sinkronizacije, rclone
ostavi `Modul 1&2 Split.xlsx.conflict1`. Skripte takvu datoteku **ne
obrađuju** i javljaju je u logu. Usporediš je s originalom i obrišeš onu
koja ne treba.

Najlakše je izbjeći: ne drži tablicu otvorenu u Excelu dok server radi.

### Grana

Server radi na grani `server`, Mac na `emmett`. Tako promjene za server ne
diraju Mac dok se ne pokažu ispravnima. Kad se ustali, spojit ćemo ih u
jednu granu.

---

## Odlazni mail

Hetzner zatvara odlazne portove 465 i 25 (mjera protiv neželjene pošte), a
587 ostavlja otvoren. Zato u `config.json` i `bank_solo/config.json` stoji:

```json
"smtp_port": 587
```

Bez toga slanje tiho istekne (`[Errno 110] Connection timed out`), dok
čitanje prijava radi - IMAP ide na svoj port, 993, koji nije blokiran. To je
podmukla kombinacija: sustav izgleda živ, prijave stižu, a ništa ne izlazi.

Način šifriranja bira `posta.py` po portu; vidi glavni README.

## Web pregled

Uz poslove na serveru stoji i stranica za mobitel — tečajevi, prijavljeni,
kome manjka uplata, što je poslano i greške iz logova. Samo za čitanje.

Upute su u [`web/README.md`](../web/README.md). Ukratko: `gunicorn` sluša na
`127.0.0.1:8099` pod systemd-om, Tailscale ga objavljuje preko HTTPS-a —
samo unutar privatne mreže, nikad na internetu — a podatke čita iz snimke
koju svakih dvadeset minuta napravi `server/osvjezi.sh`.

Tipke na stranici ne rade posao same. Ostave zahtjev u `~/zahtjevi`, a
`server/izvrsi.py` ga odradi kroz `pokreni.sh` — pod istom bravom kao i
cron. Pokreće ga systemd čim se zahtjev pojavi (`emmett-zahtjev.path`).
