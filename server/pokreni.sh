#!/bin/bash
# Pokreni jednu Emmett skriptu sa svjezim podacima iz Dropboxa.
#
#   ./pokreni.sh zoho_to_excel.py
#   ./pokreni.sh napravi_certifikate.py --pregled
#
# Redoslijed je uvijek isti: povuci iz Dropboxa -> odradi posao -> vrati u
# Dropbox. Sve troje pod jednom bravom, pa se dva cron posla nikad ne
# preklope ni medjusobno ni sa sinkronizacijom.
set -euo pipefail

KORIJEN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$KORIJEN/server/postavke.sh"

if [ $# -eq 0 ]; then
    echo "Upotreba: $0 <skripta.py> [argumenti]" >&2
    exit 2
fi

SKRIPTA="$1"; shift

# flock drzi bravu dok traje cijeli blok; -w ceka najvise CEKANJE sekundi, pa
# odustane umjesto da se poslovi nagomilaju.
#
# Posao koji se vrti cesto treba kratko cekanje: ako brava nije slobodna za
# nekoliko minuta, nema smisla da ga docekaju jos tri njegova nasljednika.
# Zato se zadaje iz crontaba: BRAVA_CEKANJE=300 pokreni.sh zoho_to_excel.py
CEKANJE="${BRAVA_CEKANJE:-1800}"

exec flock -w "$CEKANJE" "$BRAVA" bash -c '
    set -euo pipefail
    KORIJEN="$1"; SKRIPTA="$2"; shift 2
    echo "=== $(date "+%Y-%m-%d %H:%M:%S") $SKRIPTA $* ==="
    "$KORIJEN/server/sinkroniziraj.sh" >/dev/null
    cd "$KORIJEN"
    status=0
    "$PYTHON" "$SKRIPTA" "$@" || status=$?
    "$KORIJEN/server/sinkroniziraj.sh" >/dev/null
    exit $status
' _ "$KORIJEN" "$SKRIPTA" "$@"
