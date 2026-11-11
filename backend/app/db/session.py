"""SQLAlchemy engine and session factory.

The engine is configured from ``Settings.database_url`` (see
``app.core.config``). All database access should flow through the shared
business logic in ``app.services``.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.url import normalize_database_url

settings = get_settings()

engine: Engine = create_engine(
    normalize_database_url(settings.database_url),
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    pool_recycle=settings.db_pool_recycle_seconds,
    connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    hide_parameters=True,
)
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)
