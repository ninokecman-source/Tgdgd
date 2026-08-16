"""SQLite baza koja pamti koji su Cliniko računi već poslani u Solo (zaštita od dupliciranja)."""

import sqlite3
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_invoices (
    cliniko_invoice_id TEXT PRIMARY KEY,
    solo_invoice_id     TEXT,
    solo_broj_racuna    TEXT,
    jir                 TEXT,
    zki                 TEXT,
    pdf_url             TEXT,
    processed_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class StateStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def is_processed(self, cliniko_invoice_id):
        cur = self.conn.execute(
            "SELECT 1 FROM processed_invoices WHERE cliniko_invoice_id = ?",
            (str(cliniko_invoice_id),),
        )
        return cur.fetchone() is not None

    def mark_processed(self, cliniko_invoice_id, solo_racun):
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO processed_invoices
                   (cliniko_invoice_id, solo_invoice_id, solo_broj_racuna, jir, zki, pdf_url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(cliniko_invoice_id),
                    str(solo_racun.get("id")),
                    solo_racun.get("broj_racuna"),
                    solo_racun.get("jir"),
                    solo_racun.get("zki"),
                    solo_racun.get("pdf"),
                ),
            )

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
