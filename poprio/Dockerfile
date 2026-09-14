# Poprio (Cliniko -> Solo) kao Docker kontejner - najjednostavniji deploy
# na vanjski server: samo Docker treba biti instaliran, ništa drugo.
#
#   docker build -t poprio .
#
# Inicijalizacija baze obrađenih računa (jednom, svjesan odabir - vidi README):
#   docker run --rm \
#       -v $(pwd)/config.json:/app/config.json:ro \
#       -v poprio_state:/var/lib/poprio \
#       poprio python sync.py --init-from-now
#
# Redovni rad:
#   docker run -d --name poprio --restart unless-stopped \
#       -v $(pwd)/config.json:/app/config.json:ro \
#       -v poprio_state:/var/lib/poprio \
#       poprio
#
# Imenovani volumen poprio_state MORA biti montiran - bez njega baza obrađenih
# računa nestaje sa svakim restartom kontejnera. Skripta se u tom slučaju neće
# tiho ponovno pokrenuti nego će stati i tražiti inicijalizaciju.

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

VOLUME ["/var/lib/poprio"]

CMD ["python", "sync.py", "--loop"]
