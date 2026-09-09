from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from backend.database.connection import SessionLocal


def get_db_session() -> Generator[Session, None, None]:
    """Ouvre une session par requête et la referme systématiquement."""

    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()
