"""SQLite baza koja pamti koje su bankovne transakcije već obrađene (zaštita od dupliciranja)."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_transactions (
    ref_id       TEXT PRIMARY KEY,
    amount       REAL,
    matched_name TEXT,
    solo_ponuda  TEXT,
    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processed_mails (
    uid          TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class StateStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def is_transaction_processed(self, ref_id):
        cur = self.conn.execute(
            "SELECT 1 FROM processed_transactions WHERE ref_id = ?", (ref_id,)
        )
        return cur.fetchone() is not None

    def mark_transaction_processed(self, ref_id, amount, matched_name, solo_ponuda_broj):
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO processed_transactions
                   (ref_id, amount, matched_name, solo_ponuda)
                   VALUES (?, ?, ?, ?)""",
                (ref_id, amount, matched_name, solo_ponuda_broj),
            )

    def is_mail_processed(self, uid):
        cur = self.conn.execute("SELECT 1 FROM processed_mails WHERE uid = ?", (uid,))
        return cur.fetchone() is not None

    def mark_mail_processed(self, uid):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO processed_mails (uid) VALUES (?)", (uid,)
            )

    def close(self):
        self.conn.close()
