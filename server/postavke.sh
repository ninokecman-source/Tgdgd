# Postavke Emmett sustava na serveru. Ucitava ih pokreni.sh i
# sinkroniziraj.sh. Prilagodi ako ti se putevi razlikuju.

# Mapa s tablicama na serveru (lokalna kopija Dropboxa)
PRIJAVE_LOKALNO="${PRIJAVE_LOKALNO:-$HOME/Prijave}"

# Naziv rclone remotea i mapa u njemu
DROPBOX_REMOTE="${DROPBOX_REMOTE:-dropbox:Prijave}"

# Python koji ima openpyxl i requests
PYTHON="${PYTHON:-$HOME/venv/bin/python3}"

# Datoteka brave - jedan posao u isto vrijeme
BRAVA="${BRAVA:-$HOME/.emmett.lock}"

export PRIJAVE_LOKALNO DROPBOX_REMOTE PYTHON BRAVA
