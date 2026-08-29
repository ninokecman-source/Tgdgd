# Poprio (Cliniko -> Solo) kao Docker kontejner - najjednostavniji deploy
# na vanjski server: samo Docker treba biti instaliran, ništa drugo.
#
#   docker build -t poprio .
#   docker run -d --name poprio --restart unless-stopped \
#       -v $(pwd)/config.json:/app/config.json \
#       -v poprio_state:/app/state \
#       poprio

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

VOLUME ["/app/state"]

CMD ["python", "sync.py", "--loop"]
