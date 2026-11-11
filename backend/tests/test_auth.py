"""Owner-session, REST authorization, CSRF, and MCP bearer tests."""

from dataclasses import replace
from collections import deque
import time
from starlette.responses import Response

import pytest
from fastapi.testclient import TestClient

from app.api import health as health_module
from app.core.auth import (
    InvalidOwnerPassword,
    LoginRateLimited,
    MAX_FAILED_LOGIN_KEYS,
    SESSION_COOKIE_NAME,
    OwnerAuthService,
)
from app.core.config import get_settings
from app.main import app

pytestmark = pytest.mark.anyio

ORIGIN = "http://localhost:5173"
VALID_CREATE = {
    "title": "Authentication test",
    "hypothesis": "Owner-only access protects experiment data",
    "target_audience": "GrowthLoop owner",
    "channel": "email",
    "success_metric": "Signups per week",
}


@pytest.fixture()
def auth_client():
    with TestClient(app) as client:
        yield client


def _login(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"password": get_settings().owner_password},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response


async def test_correct_owner_password_issues_httponly_session(auth_client):
    response = _login(auth_client)

    assert response.json()["authenticated"] is True
    assert response.json()["csrf_token"]
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "secure" not in cookie_header
    assert get_settings().owner_password not in response.text
    assert auth_client.get("/api/v1/auth/session").json()["authenticated"] is True


def test_production_owner_cookie_is_secure():
    auth_service = OwnerAuthService(
        get_settings().owner_password,
        session_ttl_seconds=3600,
        secure_cookie=True,
        allowed_origins=[ORIGIN],
    )
    response = Response()
    auth_service.set_session_cookie(response, "opaque-test-session")

    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


async def test_incorrect_owner_password_returns_generic_error(auth_client):
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"password": "incorrect password"},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert "password" not in response.text.lower()


async def test_login_rejects_disallowed_origin(auth_client):
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"password": get_settings().owner_password},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert "password" not in response.text.lower()


async def test_repeated_password_failures_are_rate_limited(auth_client):
    auth_service = auth_client.app.state.owner_auth
    for _ in range(5):
        with pytest.raises(InvalidOwnerPassword):
            auth_service.login("wrong password", "auth-rate-test")
    with pytest.raises(LoginRateLimited):
        auth_service.login("wrong password", "auth-rate-test")


def test_login_failure_bucket_count_is_hard_bounded():
    auth_service = OwnerAuthService(
        get_settings().owner_password,
        session_ttl_seconds=3600,
        secure_cookie=False,
        allowed_origins=[ORIGIN],
    )
    now = time.monotonic()
    auth_service._failed_logins = {
        f"source-{index}": deque([now])
        for index in range(MAX_FAILED_LOGIN_KEYS)
    }

    with pytest.raises(LoginRateLimited):
        auth_service.login(get_settings().owner_password, "new-source")

    assert len(auth_service._failed_logins) == MAX_FAILED_LOGIN_KEYS


async def test_unauthenticated_rest_reads_and_writes_are_rejected(auth_client):
    read = auth_client.get("/api/v1/experiments")
    write = auth_client.post(
        "/api/v1/experiments",
        json=VALID_CREATE,
    )

    assert read.status_code == 401
    assert write.status_code == 401
    assert "password" not in read.text.lower() + write.text.lower()


async def test_invalid_and_expired_sessions_are_rejected(auth_client):
    auth_client.cookies.set(SESSION_COOKIE_NAME, "not-a-valid-session")
    assert auth_client.get("/api/v1/experiments").status_code == 401

    auth_client.cookies.clear()
    response = _login(auth_client)
    session_id = auth_client.cookies.get(SESSION_COOKIE_NAME)
    service = auth_client.app.state.owner_auth
    session_key = service._session_key(session_id)
    service._sessions[session_key] = replace(
        service._sessions[session_key], expires_at=time.monotonic() - 1
    )

    assert auth_client.get("/api/v1/auth/session").json() == {
        "authenticated": False,
        "csrf_token": None,
    }
    assert auth_client.get("/api/v1/experiments").status_code == 401
    assert response.json()["authenticated"] is True


async def test_logout_requires_csrf_and_revokes_the_session(auth_client):
    response = _login(auth_client)
    session_id = auth_client.cookies.get(SESSION_COOKIE_NAME)

    denied = auth_client.post("/api/v1/auth/logout")
    assert denied.status_code == 403

    auth_client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    logged_out = auth_client.post("/api/v1/auth/logout")

    assert logged_out.status_code == 200
    assert logged_out.json() == {"authenticated": False}
    assert auth_client.app.state.owner_auth.get_session(session_id) is None
    assert auth_client.get("/api/v1/experiments").status_code == 401


async def test_authenticated_rest_reads_and_writes_work(api_client):
    created = api_client.post("/api/v1/experiments", json=VALID_CREATE)

    assert created.status_code == 201
    experiment_id = created.json()["id"]
    assert api_client.get(f"/api/v1/experiments/{experiment_id}").status_code == 200


async def test_rest_writes_reject_missing_csrf_and_accept_current_token(api_client):
    csrf_token = api_client.headers.pop("X-CSRF-Token")
    rejected = api_client.post("/api/v1/experiments", json=VALID_CREATE)

    assert rejected.status_code == 403
    api_client.headers["X-CSRF-Token"] = csrf_token
    accepted = api_client.post("/api/v1/experiments", json=VALID_CREATE)

    assert accepted.status_code == 201


async def test_health_and_readiness_remain_public(auth_client, migrated_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(health_module, "SessionLocal", sessionmaker(bind=migrated_engine))

    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/health/ready").status_code == 200


async def test_mcp_rejects_missing_invalid_and_malformed_bearer_tokens(auth_client):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "auth-test", "version": "1"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream"}
    missing = auth_client.post("/mcp", json=payload, headers=headers)
    invalid = auth_client.post(
        "/mcp", json=payload, headers={**headers, "Authorization": "Bearer invalid-token"}
    )
    malformed = auth_client.post(
        "/mcp", json=payload, headers={**headers, "Authorization": "Bearer two parts"}
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert malformed.status_code == 401
    for response in (missing, invalid, malformed):
        assert "traceback" not in response.text.lower()
        assert "token" not in response.text.lower() or "invalid_token" in response.text
