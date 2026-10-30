#!/bin/bash
# Uskladi lokalnu kopiju Prijava s Dropboxom (rclone bisync, u oba smjera).
#
# Pokrece se prije i poslije svakog posla, pod istim zakljucavanjem kao i
# sami poslovi - da se ne dogodi da skripta pise u tablicu dok je
# sinkronizacija mijenja.
#
# Prvo pokretanje IKAD mora biti s --resync, da rclone upamti polazno
# stanje:  ./sinkroniziraj.sh --resync
#
# Razina NOTICE: uredan prolaz ne ispisuje nista, pa log ostaje citljiv i
# provjera logova ne tone u rclone poruke. Greske i upozorenja se i dalje
# vide.
#
# --resilient: bez njega jedna jedina greska kod Dropboxa srusi sve dok
# covjek ne dode i ne pokrene --resync rukom. Bilo je tako 30.10.2026: u
# 00:30 je Dropbox vratio 500 dok je rclone citao mapu, bisync je prekinuo i
# obrisao polazne popise, pa je iducih osam sati svaki pokusaj padao na
# "cannot find prior listings" - a kako pokreni.sh sinkronizira prije posla,
# s njim je stao i cron: prijave, podsjetnici, sve. S --resilient takav
# prolaz i dalje padne, ali se sljedeci sam oporavi.
#
# --recover: isto to za slucaj da sinkronizaciju presijece gasenje servera.
# --max-lock: bisync inace ostavi vjecnu bravu ako ga netko ubije nasilno.
set -euo pipefail

KORIJEN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$KORIJEN/server/postavke.sh"

mkdir -p "$PRIJAVE_LOKALNO"

exec rclone bisync "$PRIJAVE_LOKALNO" "$DROPBOX_REMOTE" \
    --create-empty-src-dirs \
    --conflict-resolve none \
    --conflict-suffix conflict \
    --max-delete 25 \
    --check-access=false \
    --resilient \
    --recover \
    --max-lock 2m \
    --log-level NOTICE \
    "$@"
