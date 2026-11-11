"""Database URL helpers shared by the application and Alembic."""

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


def normalize_database_url(database_url: str) -> URL:
    """Select psycopg 3 while preserving provider URL components and options.

    Managed PostgreSQL providers commonly supply ``postgresql://`` URLs,
    which SQLAlchemy otherwise interprets as its psycopg2 dialect. Parsing
    into a SQLAlchemy URL first preserves percent-encoded credentials and
    SSL parameters when selecting the installed psycopg 3 driver.
    """
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise ValueError("DATABASE_URL is not a valid SQLAlchemy URL") from None

    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")

    if url.drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must use PostgreSQL with psycopg 3")
    return url
