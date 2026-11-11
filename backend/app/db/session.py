"""SQLAlchemy engine and session factory.

The engine is configured from ``Settings.database_url`` (see
``app.core.config``). All database access should flow through the shared
business logic in ``app.services``.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)
