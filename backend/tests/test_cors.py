"""Tests for the CORS configuration used by the browser dashboard.

These use the health endpoint only, so they run without a database.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_preflight_from_allowed_origin_is_accepted() -> None:
    client = TestClient(app)
    response = client.options(
        "/api/v1/experiments",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
    assert "GET" in response.headers["access-control-allow-methods"]


def test_response_includes_allow_origin_for_allowed_origin() -> None:
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )


def test_disallowed_origin_gets_no_cors_headers() -> None:
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://example.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
