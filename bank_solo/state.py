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

CREATE TABLE IF NOT EXISTS notified_unmatched (
    ref_id       TEXT PRIMARY KEY,
    notified_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Nepovezane uplate, s podacima. Dosad se pamtila samo oznaka transakcije
-- (notified_unmatched), pa su podaci o uplati ostajali jedino u mailu
-- izvoda - a izvod se cita samo jednom. Tko nije prepoznat tog trena, bio
-- je izgubljen za sustav. Ovdje cekaju da im se rekne cije su.
CREATE TABLE IF NOT EXISTS unmatched_transactions (
    ref_id       TEXT PRIMARY KEY,
    date         TEXT,
    amount       REAL,
    name         TEXT,
    description  TEXT,
    razlog       TEXT,
    seen_at      TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at  TEXT,
    resolved_to  TEXT
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

    def is_unmatched_notified(self, ref_id):
        cur = self.conn.execute(
            "SELECT 1 FROM notified_unmatched WHERE ref_id = ?", (ref_id,)
        )
        return cur.fetchone() is not None

    def mark_unmatched_notified(self, ref_id):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO notified_unmatched (ref_id) VALUES (?)", (ref_id,)
            )

    # --- Nepovezane uplate ---------------------------------------------

    def remember_unmatched(self, tx, razlog=""):
        """Zapamti uplatu koja nije prepoznata. Ako vec stoji, ostaje kakva
        je - prvi zapis nosi datum kad je stigla."""
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO unmatched_transactions
                   (ref_id, date, amount, name, description, razlog)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tx.get("ref_id", ""), tx.get("date", ""), tx.get("amount", 0),
                 tx.get("name", ""), tx.get("description", ""), razlog),
            )

    def open_unmatched(self):
        """Uplate koje jos cekaju da im se rekne cije su, najnovije prve."""
        cur = self.conn.execute(
            """SELECT ref_id, date, amount, name, description, razlog, seen_at
               FROM unmatched_transactions
               WHERE resolved_at IS NULL
               ORDER BY seen_at DESC, rowid DESC"""
        )
        stupci = [o[0] for o in cur.description]
        return [dict(zip(stupci, red)) for red in cur.fetchall()]

    def get_unmatched(self, ref_id):
        cur = self.conn.execute(
            """SELECT ref_id, date, amount, name, description, razlog,
                      seen_at, resolved_at, resolved_to
               FROM unmatched_transactions WHERE ref_id = ?""", (ref_id,)
        )
        red = cur.fetchone()
        if red is None:
            return None
        return dict(zip([o[0] for o in cur.description], red))

    def resolve_unmatched(self, ref_id, komu):
        with self.conn:
            self.conn.execute(
                """UPDATE unmatched_transactions
                   SET resolved_at = datetime('now'), resolved_to = ?
                   WHERE ref_id = ?""", (komu, ref_id),
            )

    def close(self):
        self.conn.close()
