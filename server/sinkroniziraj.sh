#!/bin/bash
# Uskladi lokalnu kopiju Prijava s Dropboxom (rclone bisync, u oba smjera).
#
# Pokrece se prije i poslije svakog posla, pod istim zakljucavanjem kao i
# sami poslovi - da se ne dogodi da skripta pise u tablicu dok je
# sinkronizacija mijenja.
#
# Prvo pokretanje IKAD mora biti s --resync, da rclone upamti polazno
# stanje:  ./sinkroniziraj.sh --resync
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
    --log-level INFO \
    "$@"
