"""Connexion à la base de données (SQLite en local, PostgreSQL/Supabase en production)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import parametres


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _normaliser_url(url: str) -> str:
    # Supabase et Render fournissent souvent des URL « postgres:// » ou « postgresql:// ».
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def moteur(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None or url is not None:
        url = _normaliser_url(url or parametres().database_url)
        options = {}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, future=True, **options)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(conn, _):  # pragma: no cover - configuration
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def initialiser_base(url: str | None = None) -> Engine:
    """Crée les tables si elles n'existent pas."""
    from . import models  # noqa: F401  (enregistre les modèles)

    eng = moteur(url)
    Base.metadata.create_all(eng)
    return eng


@contextmanager
def session() -> Iterator[Session]:
    if _SessionLocal is None:
        moteur()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def nouvelle_session() -> Session:
    if _SessionLocal is None:
        moteur()
    assert _SessionLocal is not None
    return _SessionLocal()
