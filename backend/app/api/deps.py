"""FastAPI dependencies shared by the API routers."""

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import OwnerSession, SESSION_COOKIE_NAME
from app.db.session import SessionLocal


def get_db_session() -> Iterator[Session]:
    """Yield a database session that is closed when the request ends."""
    with SessionLocal() as session:
        yield session


def require_owner_session(request: Request) -> OwnerSession:
    """Require a live owner session for protected REST routes."""
    auth_service = request.app.state.owner_auth
    session = auth_service.get_session(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Session"},
        )
    return session


def require_csrf_token(
    request: Request,
    session: OwnerSession = Depends(require_owner_session),
) -> None:
    """Require the synchronizer token on authenticated state changes."""
    if not request.app.state.owner_auth.verify_csrf(
        session, request.headers.get("x-csrf-token")
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
