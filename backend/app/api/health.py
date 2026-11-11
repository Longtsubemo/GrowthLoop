"""Health-check endpoint."""

from fastapi import APIRouter
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
def health_check() -> dict[str, str]:
    """Report service liveness."""
    return {"status": "ok"}


@health_router.get("/health/ready")
def readiness_check() -> dict[str, str]:
    """Report readiness only when PostgreSQL can answer a simple query."""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503, detail="Database is unavailable"
        ) from None
    return {"status": "ready"}
