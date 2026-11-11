"""Owner login, logout, and session endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import require_csrf_token, require_owner_session
from app.core.auth import (
    InvalidOwnerPassword,
    LoginRateLimited,
    SESSION_COOKIE_NAME,
)

auth_router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@auth_router.get("/session")
def current_session(
    request: Request, response: Response
) -> dict[str, str | bool | None]:
    """Report authentication state and return the in-memory CSRF token."""
    response.headers["Cache-Control"] = "no-store"
    auth_service = request.app.state.owner_auth
    session = auth_service.get_session(
        request.cookies.get(SESSION_COOKIE_NAME)
    )
    if session is None:
        return {"authenticated": False, "csrf_token": None}
    return {"authenticated": True, "csrf_token": session.csrf_token}


@auth_router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, str | bool]:
    """Authenticate the configured owner and issue an HttpOnly session cookie."""
    _require_allowed_origin(request)
    auth_service = request.app.state.owner_auth
    if not auth_service.is_configured:
        raise HTTPException(status_code=503, detail="Owner login is not configured")

    try:
        session_id, session = auth_service.login(
            payload.password,
            request.client.host if request.client else "unknown",
        )
    except LoginRateLimited:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": "900"},
        ) from None
    except InvalidOwnerPassword:
        raise HTTPException(status_code=401, detail="Invalid credentials") from None

    auth_service.set_session_cookie(response, session_id)
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True, "csrf_token": session.csrf_token}


@auth_router.post("/logout", dependencies=[Depends(require_csrf_token)])
def logout(request: Request, response: Response) -> dict[str, bool]:
    """Revoke the active session and clear its cookie."""
    auth_service = request.app.state.owner_auth
    auth_service.logout(request.cookies.get(SESSION_COOKIE_NAME))
    auth_service.clear_session_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}


def _require_allowed_origin(request: Request) -> None:
    """Reject cross-site login attempts, including simple HTML form posts."""
    origin = request.headers.get("origin")
    if origin is None:
        if request.app.state.production:
            raise HTTPException(status_code=403, detail="Request origin is required")
        return
    if origin not in request.app.state.allowed_origins:
        raise HTTPException(status_code=403, detail="Request origin is not allowed")
