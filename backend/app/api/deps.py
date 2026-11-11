"""FastAPI dependencies shared by the API routers."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_db_session() -> Iterator[Session]:
    """Yield a database session that is closed when the request ends."""
    with SessionLocal() as session:
        yield session
