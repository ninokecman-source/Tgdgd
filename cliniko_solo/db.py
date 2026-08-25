"""DB engine/session setup. Swap `db_url` in config.json to point at
Postgres instead of the default local SQLite file — no code changes needed.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .models import Base


def make_engine(db_url: str):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return engine


def make_session(db_url: str) -> Session:
    return Session(make_engine(db_url))
