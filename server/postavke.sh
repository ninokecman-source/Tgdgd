# Postavke Emmett sustava na serveru. Ucitava ih pokreni.sh i
# sinkroniziraj.sh. Prilagodi ako ti se putevi razlikuju.

# Nove datoteke nastaju kao 600, mape kao 700. Zadani umask daje 644, pa bi
# tablice s adresama polaznika, log.txt i sync.log na serveru mogao procitati
# i svaki drugi korisnik - a na ovom serveru stoji i Cliniko. Ucitava se u
# pokreni.sh i sinkroniziraj.sh, dakle vrijedi za sve cron poslove i za rclone.
umask 077

# Mapa s tablicama na serveru (lokalna kopija Dropboxa)
PRIJAVE_LOKALNO="${PRIJAVE_LOKALNO:-$HOME/Prijave}"

# Naziv rclone remotea i mapa u njemu
DROPBOX_REMOTE="${DROPBOX_REMOTE:-dropbox:Prijave}"

# Python koji ima openpyxl i requests
PYTHON="${PYTHON:-$HOME/venv/bin/python3}"

# Datoteka brave - jedan posao u isto vrijeme
BRAVA="${BRAVA:-$HOME/.emmett.lock}"

export PRIJAVE_LOKALNO DROPBOX_REMOTE PYTHON BRAVA
