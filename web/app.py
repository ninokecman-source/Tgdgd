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
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, redirect, render_template, request, session, url_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lozinka

KORIJEN = Path(__file__).resolve().parent.parent
CONFIG = KORIJEN / "config.json"
SNIMKA = Path(__file__).resolve().parent / "stanje.json"

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
                           prosli=prosli[:6],
                           duznika=sum(t["duznika"] for t in dolazi),
                           prijavljenih=sum(t["polaznika"] for t in dolazi))


@app.route("/tecaj/<oznaka>")
@treba_prijava
def tecaj(oznaka):
    podaci = snimka()
    nadjen = next((t for t in podaci["tecajevi"] if t["oznaka"] == oznaka), None)
    if nadjen is None:
        abort(404)
    slanja = podaci.get("slanja", {})
    datoteka = nadjen["datoteka"]
    return render_template(
        "tecaj.html", podaci=podaci, tecaj=nadjen,
        podsjetnici=slanja.get("podsjetnici", {}).get(datoteka, []),
        tablica=slanja.get("tablice", {}).get(datoteka),
        napravljeni=slanja.get("certifikati_napravljeni", {}).get(datoteka),
        poslani=slanja.get("certifikati_poslani", {}).get(datoteka))


@app.route("/uplate")
@treba_prijava
def uplate():
    podaci = snimka()
    duznici = [(t, p) for t in podaci["tecajevi"] if t["stanje"] != "prosao"
               for p in t["polaznici"] if p["manjka"] > 0]
    return render_template("uplate.html", podaci=podaci, duznici=duznici)


@app.route("/stanje")
@treba_prijava
def stanje():
    return render_template("stanje.html", podaci=snimka())


@app.errorhandler(404)
def nema(_):
    return render_template("nema.html"), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099, debug=False)
