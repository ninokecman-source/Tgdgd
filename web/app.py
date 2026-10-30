"""
Web pregled Emmett sustava - samo za čitanje.

Pokazuje ono što se inače gleda po terminalu i mailovima: tečajeve i
prijavljene, kome manjka uplata, što je zadnje poslano, proknjižene uplate i
greške iz logova. Ništa ne pokreće i ništa ne mijenja - tipke dolaze kasnije.

Podaci se NE čitaju iz Excel tablica, nego iz snimke koju napravi
web/skupi.py (vidi objašnjenje u toj datoteci). Ako snimka zastari, to se
vidi na vrhu svake stranice.

Pokretanje za probu:

    ~/venv/bin/python ~/Tgdgd/web/app.py          # http://127.0.0.1:8099

U pogonu ga vodi gunicorn pod systemd-om (web/emmett-web.service), a nginx
ga objavljuje preko HTTPS-a (web/nginx-emmett.conf).
"""

import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, redirect, render_template, request, send_file, session, url_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lozinka

KORIJEN = Path(__file__).resolve().parent.parent
CONFIG = KORIJEN / "config.json"
SNIMKA = Path(__file__).resolve().parent / "stanje.json"

# Tipke na stranici ne rade posao, nego ovdje ostave zahtjev. Posao odradi
# server/izvrsi.py, kojeg systemd pokrene čim se datoteka pojavi. Jedina mapa
# u koju web smije pisati - vidi komentar u web/emmett-web.service.
ZAHTJEVI = Path(os.environ.get("EMMETT_ZAHTJEVI", Path.home() / "zahtjevi"))
ISHODI = Path(__file__).resolve().parent / "zahtjevi.json"

# Snimka starija od ovoga znači da skupi.py nije prošao - cron stoji,
# sinkronizacija je pukla ili je posao ostao zaglavljen na bravi.
ZASTARJELO_MIN = 90

# Zaštita od pogađanja lozinke: nakon toliko promašaja s iste adrese slijedi
# pauza. Pamti se u memoriji - restart web poslužitelja je briše, što je u
# redu jer restart može samo onaj koji već ima pristup serveru.
MAX_PROMASAJA = 5
PAUZA_SEK = 15 * 60

app = Flask(__name__)


def ucitaj_config() -> dict:
    if not CONFIG.exists():
        sys.exit(f"Nedostaje {CONFIG}.")
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


config = ucitaj_config()
if not config.get("web_password_hash") or not config.get("web_secret_key"):
    sys.exit("Lozinka za web pregled nije postavljena. Pokreni:\n"
             "    ~/venv/bin/python ~/Tgdgd/web/postavi_lozinku.py")

app.secret_key = config["web_secret_key"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Kolačić samo preko HTTPS-a. Za probu na 127.0.0.1 (bez posrednika)
    # stavi EMMETT_WEB_HTTP=1 u okolinu.
    SESSION_COOKIE_SECURE=not os.environ.get("EMMETT_WEB_HTTP"),
    # Prijava traje mjesec dana. Stranici ionako može prići samo uređaj u
    # Tailscale mreži, pa nema smisla tražiti lozinku svaki put na mobitelu.
    PERMANENT_SESSION_LIFETIME=timedelta(days=config.get("web_session_days", 30)),
)

promasaji = {}


# --- Prijava ---------------------------------------------------------------


def token() -> str:
    """Tajna koja mora doći natrag uz svaki obrazac. Kolačić je SameSite=Lax,
    pa tuđa stranica ionako ne može poslati obrazac u tvoje ime - ovo je
    druga brava na istim vratima."""
    if "token" not in session:
        session["token"] = secrets.token_urlsafe(32)
    return session["token"]


def token_valja() -> bool:
    poslano = request.form.get("token", "")
    return bool(poslano) and secrets.compare_digest(poslano, session.get("token", ""))


def treba_prijava(f):
    @wraps(f)
    def omot(*args, **kwargs):
        if not session.get("prijavljen"):
            return redirect(url_for("prijava", dalje=request.path))
        return f(*args, **kwargs)
    return omot


def tko_kuca() -> str:
    """Po čemu se broje promašaji prijave.

    Iza Tailscalea su svi zahtjevi s 127.0.0.1, pa adresa ništa ne razlikuje;
    zato se prvo gleda 'Tailscale-User-Login', koji Tailscale postavlja sam i
    odbacuje ako ga klijent pošalje. Iza nginxa vrijedi X-Real-IP, iz istog
    razloga: nginx ga prepisuje. X-Forwarded-For se namjerno NE koristi -
    njemu klijent može dopisati prvi član i tako bježati od pauze."""
    return (request.headers.get("Tailscale-User-Login")
            or request.headers.get("X-Real-IP")
            or request.remote_addr or "?")


def sigurno_dalje(putanja: str) -> str:
    """Samo putanja unutar ove stranice. '//tudje.com' i '/\\tudje.com'
    pregledniku su vanjske adrese, pa prolazi jedino običan put."""
    if re.fullmatch(r"/[A-Za-z0-9/_.-]*", putanja or "") and not putanja.startswith("//"):
        return putanja
    return url_for("pregled")


def pauziran(ip: str) -> int:
    """Koliko sekundi još traje pauza za tu adresu (0 ako ne traje)."""
    broj, do_kada = promasaji.get(ip, (0, 0))
    return max(0, int(do_kada - time.time())) if broj >= MAX_PROMASAJA else 0


@app.route("/prijava", methods=["GET", "POST"])
def prijava():
    ip = tko_kuca()
    ostalo = pauziran(ip)
    if ostalo:
        return render_template("prijava.html",
                              greska=f"Previše neuspjelih pokušaja. Pokušaj za "
                                     f"{ostalo // 60 + 1} min."), 429

    if request.method == "POST":
        korisnik = request.form.get("korisnik", "")
        tajna = request.form.get("lozinka", "")
        dobro = (korisnik == config.get("web_user")
                 and lozinka.provjeri(config["web_password_hash"], tajna))
        if dobro:
            promasaji.pop(ip, None)
            session.clear()
            session["prijavljen"] = True
            session.permanent = True
            return redirect(sigurno_dalje(request.form.get("dalje")))

        sada = time.time()
        # pospremi istekle, da popis ne raste bez kraja
        for adr, (_, do_kada) in list(promasaji.items()):
            if do_kada < sada:
                del promasaji[adr]
        broj, _ = promasaji.get(ip, (0, 0))
        promasaji[ip] = (broj + 1, sada + PAUZA_SEK)
        return render_template("prijava.html", greska="Pogrešno ime ili lozinka.",
                               dalje=request.form.get("dalje", "")), 401

    return render_template("prijava.html", dalje=request.args.get("dalje", ""))


@app.route("/odjava")
def odjava():
    session.clear()
    return redirect(url_for("prijava"))


# --- Podaci ----------------------------------------------------------------


def snimka() -> dict:
    """Snimku čita svaki zahtjev - datoteka je mala, a tako se nova vidi
    odmah, bez restarta."""
    if not SNIMKA.exists():
        return {"nema_snimke": True, "tecajevi": [], "greske": [], "prolazi": [],
                "logovi": [], "upozorenja": [], "slanja": {}, "uplate": {}}
    with open(SNIMKA, encoding="utf-8") as f:
        podaci = json.load(f)
    podaci["nema_snimke"] = False
    podaci["starost_min"] = starost_minuta(podaci.get("snimljeno"))
    podaci["zastarjelo"] = (podaci["starost_min"] is None
                            or podaci["starost_min"] > ZASTARJELO_MIN)
    return podaci


def starost_minuta(kada: str):
    if not kada:
        return None
    try:
        return int((datetime.now() - datetime.fromisoformat(kada)).total_seconds() // 60)
    except ValueError:
        return None


@app.context_processor
def ugradi_token():
    return {"token": token() if session.get("prijavljen") else "",
            "ima_wordmark": (mapa_marke() / "wordmark-navy.svg").is_file()}


@app.template_filter("vrijeme")
def filtar_vrijeme(vrijednost):
    """ISO zapis u '14.10.2026. 13:40'."""
    if not vrijednost:
        return "-"
    try:
        return datetime.fromisoformat(str(vrijednost).replace(" ", "T")).strftime("%d.%m.%Y. %H:%M")
    except ValueError:
        return str(vrijednost)


@app.template_filter("datum")
def filtar_datum(vrijednost):
    if not vrijednost:
        return "-"
    try:
        return datetime.fromisoformat(str(vrijednost)).strftime("%d.%m.%Y.")
    except ValueError:
        return str(vrijednost)


@app.template_filter("eur")
def filtar_eur(vrijednost):
    try:
        return f"{float(vrijednost):,.2f} €".replace(",", " ").replace(".", ",", 1)
    except (TypeError, ValueError):
        return "-"


# --- Zahtjevi (tipke) ------------------------------------------------------


def ucitaj_ishode() -> list:
    """Ishodi poslova koje je upisao server/izvrsi.py. Web ih samo čita."""
    if not ISHODI.exists():
        return []
    try:
        with open(ISHODI, encoding="utf-8") as f:
            podaci = json.load(f)
        return podaci if isinstance(podaci, list) else []
    except (ValueError, OSError):
        return []


def zadnji_ishod(tablica: str):
    nasi = [i for i in ucitaj_ishode() if i.get("tablica") == tablica]
    if not nasi:
        return None
    ishod = max(nasi, key=lambda i: i.get("trazeno", ""))
    ishod["u_tijeku"] = ishod.get("status") == "u tijeku"
    return ishod


def ceka_zahtjev(tablica: str) -> bool:
    """Postoji li zahtjev koji još nije ni pokrenut."""
    if not ZAHTJEVI.is_dir():
        return False
    for put in ZAHTJEVI.glob("*.json"):
        try:
            with open(put, encoding="utf-8") as f:
                if json.load(f).get("tablica") == tablica:
                    return True
        except (ValueError, OSError):
            continue
    return False


def zatrazi(posao: str, tablica: str, **dodatno) -> None:
    """Ostavi zahtjev; posao odradi server/izvrsi.py. `dodatno` su polja koja
    taj posao treba - adresa, ime, naslov i tijelo poruke."""
    ZAHTJEVI.mkdir(parents=True, exist_ok=True)
    zahtjev = {"posao": posao, "tablica": tablica,
               "trazio": config.get("web_user", "?"),
               "kada": datetime.now().isoformat(timespec="seconds"),
               **{k: v for k, v in dodatno.items() if v}}
    naziv = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(4)}.json"
    # piši pod drugim nazivom pa preimenuj: systemd prati *.json, ne smije
    # uloviti datoteku koja se još piše
    privremeno = ZAHTJEVI / (naziv + ".pisem")
    with open(privremeno, "w", encoding="utf-8") as f:
        json.dump(zahtjev, f, ensure_ascii=False)
    privremeno.replace(ZAHTJEVI / naziv)


def nedobili(tecaj: dict, poslani) -> list:
    """Polaznici s adresom kojima potvrdnica još nije poslana."""
    vec = {a.lower() for a in (poslani or {}).get("poslano", [])}
    return [p for p in tecaj["polaznici"]
            if p["email"] and p["email"].lower() not in vec]


def mapa_tablica() -> Path:
    return Path(config["output_dir"])


# Pravi Brandon Grotesque i pravi wordmark ne mogu u repozitorij: font je
# komercijalan, a wordmark su njegova slova u obrisu, i repozitorij je javan.
# Zato stoje u mapi 'Marka' uz tablice, koju Dropbox sinkronizira na server
# kao i sve ostalo. Nema ih - stranica radi s Figtreejem i ispisanim EMMETT.
MARKA = {
    "wordmark-navy.svg": "image/svg+xml",
    "wordmark-white.svg": "image/svg+xml",
    "BrandonGrotesque-Regular.otf": "font/otf",
    "BrandonGrotesque-Medium.otf": "font/otf",
    "BrandonGrotesque-Bold.otf": "font/otf",
}


def mapa_marke() -> Path:
    return mapa_tablica() / "Marka"


@app.route("/marka/<naziv>")
def marka(naziv):
    """Datoteke marke. Namjerno bez prijave, da i sama stranica za prijavu
    bude u Emmettovu ruhu; naziv mora biti s popisa, pa se ovuda ne može doći
    ni do čega drugog u mapi s tablicama."""
    if naziv not in MARKA:
        abort(404)
    put = mapa_marke() / naziv
    if not put.is_file():
        abort(404)
    return send_file(put, mimetype=MARKA[naziv], max_age=86400)


def zadani_podsjetnik(tecaj: dict, polaznik: dict):
    """Tekst podsjetnika za uplatu, s već popunjenim imenom i iznosima."""
    import poruke
    return poruke.podsjetnik_uplata(mapa_tablica(), config, tecaj, polaznik)


def zadani_poziv():
    """Tekst poziva na tečaj. Oznake ostaju - poruka ide većem broju ljudi,
    svakome sa svojim imenom."""
    import poruke
    import predlosci
    naslov, tijelo, izvor = predlosci.dohvati(
        mapa_tablica(), "poziv na tecaj", config=config,
        kljuc_naslov="invite_subject", kljuc_tijela="invite_body",
        zadani_naslov=poruke.POZIV_NASLOV, zadano_tijelo=poruke.POZIV_TIJELO)
    return naslov, tijelo, izvor


def zadani_certifikat():
    """Tekst maila uz potvrdnicu. Ovdje oznake {first_name} OSTAJU - poruka
    ide svakom polazniku sa svojim imenom, pa se popunjavaju pri slanju."""
    import predlosci
    from posalji_certifikate import ZADANI_NASLOV, ZADANI_TEKST
    naslov, tijelo, izvor = predlosci.dohvati(
        mapa_tablica(), "mail uz certifikat", config=config,
        kljuc_naslov="certificate_mail_subject",
        kljuc_tijela="certificate_mail_body",
        zadani_naslov=ZADANI_NASLOV, zadano_tijelo=ZADANI_TEKST)
    return naslov, tijelo, izvor


def primjer_varijabli(tecaj: dict, cekaju: list) -> dict:
    """Čime se oznake popune za prvog primatelja. Služi pregledu na stranici:
    ime se povlači iz popisa samo, pa neka se to i vidi, umjesto da se vjeruje
    na riječ."""
    from send_reminders import datumi_rijecima

    prvi = cekaju[0] if cekaju else {"ime": ""}
    dijelovi = (prvi.get("ime") or "").split()
    return {
        "first_name": dijelovi[0] if dijelovi else "",
        "last_name": " ".join(dijelovi[1:]),
        "course_code": tecaj["kod"],
        "location": tecaj["mjesto"],
        "dates": tecaj["datumi"],
        "datumi_rijecima": datumi_rijecima(tecaj["datumi"]),
        "instructor_name": tecaj.get("instruktor") or config.get("instructor_name", ""),
        "link_termini": config.get("course_dates_url", ""),
    }


def nadji_polaznika(tecaj: dict, broj: int) -> dict:
    """Polaznik po mjestu u popisu. Mjesto služi samo za put do stranice -
    u zahtjev ide adresa odnosno ime, pa i ako se tablica u međuvremenu
    promijenila, posao se radi nad pravom osobom ili nad nikim."""
    if broj < 0 or broj >= len(tecaj["polaznici"]):
        abort(404)
    return tecaj["polaznici"][broj]


def nadji_tecaj(oznaka: str):
    podaci = snimka()
    nadjen = next((t for t in podaci["tecajevi"] if t["oznaka"] == oznaka), None)
    if nadjen is None:
        abort(404)
    return podaci, nadjen


# --- Stranice --------------------------------------------------------------


@app.route("/")
@treba_prijava
def pregled():
    podaci = snimka()
    tecajevi = podaci["tecajevi"]
    dolazi = [t for t in tecajevi if t["stanje"] in ("dolazi", "u toku")]
    dolazi.sort(key=lambda t: t["pocetak"] or "9999")
    prosli = [t for t in tecajevi if t["stanje"] == "prosao"]
    return render_template("pregled.html", podaci=podaci, dolazi=dolazi,
                           prosli=prosli,
                           duznika=sum(t["duznika"] for t in dolazi),
                           prijavljenih=sum(t["polaznika"] for t in dolazi))


@app.route("/tecaj/<oznaka>")
@treba_prijava
def tecaj(oznaka):
    podaci, nadjen = nadji_tecaj(oznaka)
    slanja = podaci.get("slanja", {})
    datoteka = nadjen["datoteka"]
    poslani = slanja.get("certifikati_poslani", {}).get(datoteka)
    ishod = zadnji_ishod(datoteka)
    ceka = ceka_zahtjev(datoteka)
    return render_template(
        "tecaj.html", podaci=podaci, tecaj=nadjen,
        podsjetnici=slanja.get("podsjetnici", {}).get(datoteka, []),
        tablica=slanja.get("tablice", {}).get(datoteka),
        napravljeni=slanja.get("certifikati_napravljeni", {}).get(datoteka),
        poslani=poslani,
        cekaju=nedobili(nadjen, poslani),
        za_poziv=sum(len(s["ljudi"]) for s in (nadjen.get("pozvati") or [])),
        ishod=ishod,
        radi=ceka or bool(ishod and ishod.get("u_tijeku")))


@app.route("/tecaj/<oznaka>/posalji", methods=["GET", "POST"])
@treba_prijava
def posalji(oznaka):
    """Slanje potvrdnica - jedina tipka koja nešto šalje van, pa ide preko
    zasebne potvrde s popisom primatelja."""
    podaci, tecaj = nadji_tecaj(oznaka)
    poslani = podaci.get("slanja", {}).get("certifikati_poslani", {}).get(tecaj["datoteka"])
    cekaju = nedobili(tecaj, poslani)

    if request.method == "POST":
        if not token_valja():
            abort(400)
        naslov = request.form.get("naslov", "").strip()
        tijelo = request.form.get("tijelo", "").strip()
        if cekaju and naslov and tijelo and not ceka_zahtjev(tecaj["datoteka"]):
            zatrazi("posalji_certifikate", tecaj["datoteka"],
                    naslov=naslov, tijelo=tijelo)
        return redirect(url_for("tecaj", oznaka=oznaka))

    naslov = tijelo = izvor = ""
    greska = ""
    try:
        naslov, tijelo, izvor = zadani_certifikat()
    except Exception as e:
        greska = str(e)

    return render_template("posalji.html", podaci=podaci, tecaj=tecaj,
                           cekaju=cekaju, naslov=naslov, tijelo=tijelo,
                           izvor=izvor, greska=greska,
                           primjer=primjer_varijabli(tecaj, cekaju),
                           napravljeni=podaci.get("slanja", {})
                           .get("certifikati_napravljeni", {})
                           .get(tecaj["datoteka"]))


@app.route("/tecaj/<oznaka>/pregled", methods=["POST"])
@treba_prijava
def pregled_slanja(oznaka):
    """Pregled: pokaže kome bi se slalo, bez slanja."""
    _, tecaj = nadji_tecaj(oznaka)
    if not token_valja():
        abort(400)
    if not ceka_zahtjev(tecaj["datoteka"]):
        zatrazi("pregled_certifikata", tecaj["datoteka"])
    return redirect(url_for("tecaj", oznaka=oznaka))


@app.route("/tecaj/<oznaka>/popis", methods=["POST"])
@treba_prijava
def popis_polaznika(oznaka):
    """PDF s popisom polaznika - samo imena, bez adresa i iznosa. Završi uz
    tablice, u mapi Popisi, pa ga Dropbox odnese i na mobitel."""
    _, tecaj = nadji_tecaj(oznaka)
    if not token_valja():
        abort(400)
    if not ceka_zahtjev(tecaj["datoteka"]):
        zatrazi("popis_polaznika", tecaj["datoteka"])
    return redirect(url_for("tecaj", oznaka=oznaka))


@app.route("/tecaj/<oznaka>/poziv", methods=["GET", "POST"])
@treba_prijava
def poziv(oznaka):
    """Poziv polaznicima prethodnog modula. Tko je već na ovom tečaju ili je
    već pozvan nije ni na popisu - to je odlučeno u snimci (pozivi.py)."""
    import pozivi

    podaci, tecaj = nadji_tecaj(oznaka)
    skupine = tecaj.get("pozvati") or []
    svi = {o["email"]: o for s in skupine for o in s["ljudi"]}

    if request.method == "POST":
        if not token_valja():
            abort(400)
        naslov = request.form.get("naslov", "").strip()
        tijelo = request.form.get("tijelo", "").strip()
        # ime se uzima iz snimke, ne iz obrasca - obrascu se vjeruje samo
        # koga si odabrao, ne i kako se zove
        odabrani = [svi[a] for a in request.form.getlist("kome") if a in svi]
        if odabrani and naslov and tijelo and not ceka_zahtjev(tecaj["datoteka"]):
            zatrazi("posalji_poziv", tecaj["datoteka"], naslov=naslov,
                    tijelo=tijelo, primatelji=odabrani)
        return redirect(url_for("tecaj", oznaka=oznaka))

    naslov = tijelo = izvor = ""
    greska = ""
    try:
        naslov, tijelo, izvor = zadani_poziv()
    except Exception as e:
        greska = str(e)

    prvi = next((o for s in skupine for o in s["ljudi"]), {"ime": ""})
    dijelovi = (prvi.get("ime") or "").split()
    primjer = {
        "first_name": dijelovi[0] if dijelovi else "",
        "last_name": " ".join(dijelovi[1:]),
        "course_code": tecaj["kod"],
        "location": tecaj["mjesto"],
        "dates": tecaj["datumi"],
        "prethodni_modul": pozivi.naziv_prethodnog(config, tecaj["kod"]) or "prethodni modul",
        "instructor_name": tecaj.get("instruktor") or config.get("instructor_name", ""),
        "link_termini": config.get("course_dates_url", ""),
    }

    return render_template("poziv.html", podaci=podaci, tecaj=tecaj,
                           skupine=skupine, koliko=len(svi),
                           naslov=naslov, tijelo=tijelo, izvor=izvor,
                           greska=greska, primjer=primjer,
                           prethodni=primjer["prethodni_modul"])


@app.route("/tecaj/<oznaka>/polaznik/<int:broj>/podsjetnik", methods=["GET", "POST"])
@treba_prijava
def podsjetnik(oznaka, broj):
    """Podsjetnik za uplatu jednom polazniku. Tekst se prije slanja pokaže
    popunjen i može se izmijeniti - šalje se točno ono što ostane na ekranu."""
    podaci, tecaj = nadji_tecaj(oznaka)
    polaznik = nadji_polaznika(tecaj, broj)

    if request.method == "POST":
        if not token_valja():
            abort(400)
        naslov = request.form.get("naslov", "").strip()
        tijelo = request.form.get("tijelo", "").strip()
        if polaznik["email"] and naslov and tijelo:
            zatrazi("podsjetnik_uplata", tecaj["datoteka"],
                    email=polaznik["email"], ime=polaznik["ime"],
                    naslov=naslov, tijelo=tijelo)
        return redirect(url_for("tecaj", oznaka=oznaka))

    naslov = tijelo = ""
    greska = ""
    if polaznik["email"]:
        try:
            naslov, tijelo = zadani_podsjetnik(tecaj, polaznik)
        except Exception as e:
            greska = str(e)
    return render_template("poruka.html", podaci=podaci, tecaj=tecaj,
                           polaznik=polaznik, naslov=naslov, tijelo=tijelo,
                           greska=greska, oznake=None,
                           kome=polaznik["email"],
                           naslov_stranice="Podsjetnik za uplatu",
                           gumb="Pošalji podsjetnik",
                           natrag=url_for("tecaj", oznaka=oznaka))


@app.route("/tecaj/<oznaka>/polaznik/<int:broj>/otkazi", methods=["GET", "POST"])
@treba_prijava
def otkazi(oznaka, broj):
    """Polaznik je otkazao - briše se iz tablice. Jedina radnja koja trajno
    uklanja podatak, pa ide preko potvrde."""
    podaci, tecaj = nadji_tecaj(oznaka)
    polaznik = nadji_polaznika(tecaj, broj)

    if request.method == "POST":
        if not token_valja():
            abort(400)
        if not ceka_zahtjev(tecaj["datoteka"]):
            zatrazi("otkazi_polaznika", tecaj["datoteka"],
                    email=polaznik["email"], ime=polaznik["ime"])
        return redirect(url_for("tecaj", oznaka=oznaka))

    return render_template("otkazi.html", podaci=podaci, tecaj=tecaj,
                           polaznik=polaznik)


@app.route("/uplate")
@treba_prijava
def uplate():
    podaci = snimka()
    duznici = [(t, p) for t in podaci["tecajevi"] if t["stanje"] != "prosao"
               for p in t["polaznici"] if p["manjka"] > 0]
    return render_template("uplate.html", podaci=podaci, duznici=duznici,
                           ishodi=ucitaj_ishode()[-5:][::-1])


def nepovezane(podaci: dict) -> list:
    return podaci.get("uplate", {}).get("nepovezane", []) or []


def polaznici_za_izbor(podaci: dict) -> list:
    """[(tečaj, [polaznici s adresom])] - ponuda u izborniku pri povezivanju
    uplate. Bez adrese se ne može povezati: uplata se knjiži po adresi, jer
    je ona jedina jedinstvena."""
    izbor = []
    for t in podaci["tecajevi"]:
        s_adresom = [p for p in t["polaznici"] if p["email"]]
        if s_adresom:
            izbor.append((t, s_adresom))
    return izbor


@app.route("/uplata/<int:broj>/povezi", methods=["GET", "POST"])
@treba_prijava
def povezi_uplatu(broj):
    """Nepovezana uplata - reci čija je. Knjiži se isto kao da je sustav sam
    prepoznao: Solo ponuda, iznos u tablicu, uplata više nije greška."""
    podaci = snimka()
    popis = nepovezane(podaci)
    if broj < 0 or broj >= len(popis):
        abort(404)
    uplata = popis[broj]

    if request.method == "POST":
        if not token_valja():
            abort(400)
        email = request.form.get("email", "").strip()
        tablica = ""
        for t in podaci["tecajevi"]:
            if any(p["email"].lower() == email.lower() for p in t["polaznici"] if p["email"]):
                tablica = t["datoteka"]
                break
        if email and tablica and not ceka_zahtjev(tablica):
            zatrazi("rijesi_uplatu", tablica, email=email, ref=uplata["ref"])
        return redirect(url_for("uplate"))

    return render_template("povezi.html", podaci=podaci, uplata=uplata,
                           izbor=polaznici_za_izbor(podaci))


@app.route("/stanje")
@treba_prijava
def stanje():
    return render_template("stanje.html", podaci=snimka())


@app.route("/greske/potvrdi", methods=["POST"])
@treba_prijava
def potvrdi_greske():
    """Kreni ispočetka s brojanjem grešaka: zapamti dokle su logovi
    pročitani. Logovi ostaju netaknuti - briše se samo brojač."""
    if not token_valja():
        abort(400)
    # Zahtjev bez tablice je samo ovaj posao, pa je i provjera ista kao
    # drugdje: ne šalji drugi dok prvi još čeka.
    if not ceka_zahtjev(""):
        zatrazi("potvrdi_greske", "")
    return redirect(url_for("stanje") + "#greske")


@app.errorhandler(404)
def nema(_):
    return render_template("nema.html"), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099, debug=False)
