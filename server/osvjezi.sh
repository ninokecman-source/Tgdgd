#!/bin/bash
# Povuci svjeze tablice iz Dropboxa i osvjezi snimku za web pregled.
#
# Zamjena za golu sinkronizaciju u cronu: isti posao kao prije, plus jedan
# prolaz kroz web/skupi.py, da stranica pokazuje stanje od zadnjih 20 minuta.
#
# Pokrece se pod bravom, ali NEBLOKIRAJUCE (flock -n u crontabu): ako upravo
# radi neki drugi posao, ovaj se preskoci. Sljedeci otkucaj je za 20 minuta,
# nema se sto cekati ni nagomilavati.
#
# Uspjesan prolaz namjerno ne pise u log - dokaz da je prosao je vrijeme
# datoteke web/stanje.json, a to web pregled pokazuje na svojoj prvoj
# stranici. Greske idu na stderr, pa ih cron sprema u log i provjera logova
# ih uhvati.
set -euo pipefail

KORIJEN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$KORIJEN/server/postavke.sh"

"$KORIJEN/server/sinkroniziraj.sh" >/dev/null

cd "$KORIJEN"
"$PYTHON" web/skupi.py
