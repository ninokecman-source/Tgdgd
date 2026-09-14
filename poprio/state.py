"""SQLite baza koja pamti koji su Cliniko računi već poslani u Solo (zaštita od dupliciranja).

Račun se ne upisuje tek nakon uspješnog slanja nego se **zauzima prije**
poziva prema Solu (status `pending`), pa se tek onda označi kao `done`.
Razlog: između provjere "je li već poslan" i upisa "poslan je" prođe cijeli
Solo poziv od nekoliko sekundi - dovoljno da drugi proces prođe kroz istu
provjeru i pošalje isti račun drugi put. Zauzimanje je jedan atomaran upis
(INSERT OR IGNORE nad primarnim ključem), pa kroz njega može proći samo
jedan.

Ako slanje ne uspije, zauzimanje se otpušta i račun se pokušava ponovno.
Ako proces bude ubijen usred slanja, zapis ostaje `pending` - to je stanje
u kojem se stvarno ne zna je li dokument u Solu nastao ili nije, pa se ne
pokušava ponovno automatski (to bi mogao biti duplikat) nego se javlja
operateru.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_invoices (
    cliniko_invoice_id TEXT PRIMARY KEY,
    solo_invoice_id     TEXT,
    solo_broj_racuna    TEXT,
    jir                 TEXT,
    zki                 TEXT,
    pdf_url             TEXT,
    processed_at        TEXT NOT NULL DEFAULT (datetime('now')),
    status              TEXT NOT NULL DEFAULT 'done',
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class StateStore:
    def __init__(self, db_path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # timeout: dva procesa mogu nakratko čekati jedan drugoga na upisu
        self.conn = sqlite3.connect(db_path, timeout=10)
        self.conn.executescript(SCHEMA)
        self._add_missing_columns()
        self.conn.commit()

    def _add_missing_columns(self):
        """Baze nastale prije uvođenja ovih stupaca nemaju ih. Postojeći zapisi
        su svi uspješno poslani, pa im zadani 'done' i odgovara."""
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(processed_invoices)")}
        for name, definition in (
            ("status", "TEXT NOT NULL DEFAULT 'done'"),
            ("attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("last_error", "TEXT"),
        ):
            if name not in existing:
                self.conn.execute(f"ALTER TABLE processed_invoices ADD COLUMN {name} {definition}")

    def claim(self, cliniko_invoice_id):
        """Pokušava zauzeti račun za slanje. Vraća True samo ako ga je stvarno
        zauzeo ovaj poziv - ako je već zauzet ili obrađen, vraća False."""
        with self.conn:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO processed_invoices (cliniko_invoice_id, status)
                   VALUES (?, 'pending')""",
                (str(cliniko_invoice_id),),
            )
        return cur.rowcount == 1

    def mark_done(self, cliniko_invoice_id, solo_racun):
        with self.conn:
            self.conn.execute(
                """UPDATE processed_invoices
                   SET solo_invoice_id = ?, solo_broj_racuna = ?, jir = ?, zki = ?,
                       pdf_url = ?, processed_at = datetime('now'), status = 'done'
                   WHERE cliniko_invoice_id = ?""",
                (
                    str(solo_racun.get("id")),
                    solo_racun.get("broj_racuna") or solo_racun.get("broj_ponude"),
                    solo_racun.get("jir"),
                    solo_racun.get("zki"),
                    solo_racun.get("pdf"),
                    str(cliniko_invoice_id),
                ),
            )

    def claim_retry(self, cliniko_invoice_id):
        """Zauzima ranije neuspjeli račun za ponovni pokušaj. Kao i `claim`,
        kroz ovo može proći samo jedan proces."""
        with self.conn:
            cur = self.conn.execute(
                """UPDATE processed_invoices SET status = 'pending'
                   WHERE cliniko_invoice_id = ? AND status = 'failed'""",
                (str(cliniko_invoice_id),),
            )
        return cur.rowcount == 1

    def mark_failed(self, cliniko_invoice_id, error):
        """Bilježi neuspjeh i broji pokušaje. Zapis OSTAJE u bazi - tako račun
        ne ovisi o tome je li još unutar vremenskog prozora upita prema Clinku,
        nego se ponavlja po ID-u dok ne uspije ili dok ne potroši pokušaje.
        Vraća ukupan broj dosadašnjih pokušaja."""
        with self.conn:
            self.conn.execute(
                """UPDATE processed_invoices
                   SET status = 'failed', attempts = attempts + 1, last_error = ?,
                       processed_at = datetime('now')
                   WHERE cliniko_invoice_id = ?""",
                (str(error)[:500], str(cliniko_invoice_id)),
            )
        row = self.conn.execute(
            "SELECT attempts FROM processed_invoices WHERE cliniko_invoice_id = ?",
            (str(cliniko_invoice_id),),
        ).fetchone()
        return row[0] if row else 0

    def failed_for_retry(self, max_attempts):
        return [
            row[0]
            for row in self.conn.execute(
                """SELECT cliniko_invoice_id FROM processed_invoices
                   WHERE status = 'failed' AND attempts < ?
                   ORDER BY processed_at""",
                (max_attempts,),
            )
        ]

    def exhausted_failures(self, max_attempts):
        """Računi koji su potrošili sve pokušaje - dalje traže ljudsku pažnju."""
        return list(
            self.conn.execute(
                """SELECT cliniko_invoice_id, attempts, last_error FROM processed_invoices
                   WHERE status = 'failed' AND attempts >= ?
                   ORDER BY processed_at""",
                (max_attempts,),
            )
        )

    def pending_claims(self):
        """Računi zaustavljeni u `pending` - proces je prekinut usred slanja i
        ne zna se je li dokument u Solu nastao."""
        return [
            row[0]
            for row in self.conn.execute(
                "SELECT cliniko_invoice_id FROM processed_invoices WHERE status = 'pending'"
            )
        ]

    def get_watermark(self):
        cur = self.conn.execute("SELECT value FROM sync_state WHERE key = 'last_updated_at'")
        row = cur.fetchone()
        return row[0] if row else None

    def set_watermark(self, iso_timestamp):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES ('last_updated_at', ?)",
                (iso_timestamp,),
            )

    def close(self):
        self.conn.close()
