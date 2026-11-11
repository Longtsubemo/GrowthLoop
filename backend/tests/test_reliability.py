"""Reliability tests: database outages, concurrency and duplicate requests.

Outages are simulated by pointing a throwaway engine at a closed localhost
port. PostgreSQL itself is never stopped, and the development database is
never referenced.

Run with ``pytest tests/test_reliability.py``.
"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db_session
from app.main import app
from app.core.config import get_settings
from mcp_server import server as mcp_server_module

pytestmark = pytest.mark.anyio

EXPERIMENTS_URL = "/api/v1/experiments"

# A closed port: connections fail immediately, without touching Docker.
UNREACHABLE_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@127.0.0.1:1/growthloop_unreachable"
)

LEAK_MARKERS = (
    "traceback",
    "sqlalchemy",
    "psycopg",
    "password",
    "postgresql://",
    "postgresql+psycopg",
)

VALID_CREATE: dict[str, object] = {
    "title": "Reliability experiment",
    "hypothesis": "The API reports failures without leaking internals",
    "target_audience": "Founders evaluating GrowthLoop",
    "channel": "email",
    "success_metric": "Signups per week",
}


def _broken_factory():
    engine = create_engine(
        UNREACHABLE_DATABASE_URL, connect_args={"connect_timeout": 1}
    )
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _text(result) -> str:
    return result.content[0].text if result.content else ""


def _assert_no_leak(body: str) -> None:
    lowered = body.lower()
    for marker in LEAK_MARKERS:
        assert marker not in lowered, f"leaked {marker!r} in: {body}"


def rest_create(rest, **overrides: object) -> dict:
    response = rest.post(EXPERIMENTS_URL, json={**VALID_CREATE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Database unavailable
# ---------------------------------------------------------------------------


async def test_rest_reports_database_unavailable_without_leaking() -> None:
    engine, factory = _broken_factory()

    def override_get_db_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"password": get_settings().owner_password},
                headers={"Origin": "http://localhost:5173"},
            )
            assert login.status_code == 200
            response = client.get(EXPERIMENTS_URL)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 500
    _assert_no_leak(response.text)


async def test_mcp_reports_database_unavailable_without_leaking(
    monkeypatch,
) -> None:
    engine, factory = _broken_factory()
    monkeypatch.setattr(mcp_server_module, "SessionLocal", factory)
    try:
        from mcp import Client

        async with Client(mcp_server_module.mcp, mode="legacy") as client:
            read = await client.call_tool("list_experiments", {})
            write = await client.call_tool(
                "create_experiment", dict(VALID_CREATE)
            )
    finally:
        engine.dispose()

    for result in (read, write):
        assert result.is_error
        text = _text(result)
        assert "database is unavailable" in text.lower()
        _assert_no_leak(text)


# ---------------------------------------------------------------------------
# Concurrent cross-interface updates
# ---------------------------------------------------------------------------


async def test_concurrent_cross_interface_updates_remain_consistent(
    shared_stack,
) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={"growthloop_session": rest.cookies.get("growthloop_session")},
        headers={
            "Origin": "http://localhost:5173",
            "X-CSRF-Token": rest.headers["X-CSRF-Token"],
        },
    ) as http:
        first, second, mcp_result = await asyncio.gather(
            http.patch(
                f"{EXPERIMENTS_URL}/{created['id']}",
                json={"title": "REST concurrent one"},
            ),
            http.patch(
                f"{EXPERIMENTS_URL}/{created['id']}",
                json={"title": "REST concurrent two"},
            ),
            mcp.call_tool(
                "update_experiment",
                {
                    "experiment_id": created["id"],
                    "hypothesis": "MCP concurrent hypothesis",
                },
            ),
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert not mcp_result.is_error, _text(mcp_result)

    final = rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()
    assert final["id"] == created["id"]
    assert final["title"] in {"REST concurrent one", "REST concurrent two"}
    assert final["hypothesis"] == "MCP concurrent hypothesis"


# ---------------------------------------------------------------------------
# Duplicate requests (complementary to the cross-layer cases)
# ---------------------------------------------------------------------------


async def test_repeated_rest_delete_and_mcp_status(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    first = rest.delete(f"{EXPERIMENTS_URL}/{created['id']}")
    second = rest.delete(f"{EXPERIMENTS_URL}/{created['id']}")
    assert first.status_code == 204
    assert second.status_code == 404

    created = rest_create(rest)
    for _ in range(2):
        result = await mcp.call_tool(
            "update_experiment_status",
            {"experiment_id": created["id"], "status": "planned"},
        )
        assert not result.is_error, _text(result)
        assert result.structured_content["status"] == "planned"


async def test_repeated_mcp_result_is_last_write_wins(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    for value in ("MCP first result", "MCP second result"):
        result = await mcp.call_tool(
            "record_experiment_result",
            {"experiment_id": created["id"], "actual_result": value},
        )
        assert not result.is_error, _text(result)

    assert rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()[
        "actual_result"
    ] == "MCP second result"
