"""Cross-layer integration tests: MCP and REST over the same database.

The existing suites exercise each interface in isolation. These tests wire
both interfaces to the same isolated PostgreSQL database (``shared_stack``)
so a record written through MCP must be readable through REST and vice
versa. Both interfaces are real: REST goes through the FastAPI app and the
MCP side goes through a ``ClientSession`` JSON-RPC round trip.

Run with ``pytest tests/test_integration_cross_layer.py``.
"""

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.anyio

EXPERIMENTS_URL = "/api/v1/experiments"

VALID_CREATE: dict[str, object] = {
    "title": "Cross-layer landing page test",
    "hypothesis": "A benefit-led headline increases signups",
    "target_audience": "First-time visitors from Product Hunt",
    "channel": "landing_page",
    "success_metric": "Signup conversion rate",
}

FIELDS = (
    "id",
    "title",
    "hypothesis",
    "target_audience",
    "channel",
    "budget_amount",
    "currency_code",
    "status",
    "execution_steps",
    "success_metric",
    "actual_result",
)
TIMESTAMP_FIELDS = ("created_at", "updated_at")


def _text(result) -> str:
    """The first text block of a (usually error) tool result."""
    return result.content[0].text if result.content else ""


async def call_tool(client, name: str, arguments: dict) -> dict:
    """Invoke an MCP tool and assert it succeeded."""
    result = await client.call_tool(name, arguments)
    assert not result.is_error, _text(result)
    return result.structured_content


def rest_create(rest, **overrides: object) -> dict:
    """POST a valid experiment through the REST API."""
    response = rest.post(EXPERIMENTS_URL, json={**VALID_CREATE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def _parse_timestamp(value: str) -> datetime:
    """Parse either ``...Z`` or ``...+00:00`` timestamps."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_record(rest_body: dict, mcp_body: dict) -> None:
    """The REST response and MCP structured content describe the same row."""
    assert set(rest_body) == set(mcp_body)
    for field in FIELDS:
        assert rest_body[field] == mcp_body[field], field
    for field in TIMESTAMP_FIELDS:
        assert _parse_timestamp(rest_body[field]) == _parse_timestamp(
            mcp_body[field]
        ), field


# ---------------------------------------------------------------------------
# MCP -> database -> REST
# ---------------------------------------------------------------------------


async def test_mcp_create_is_visible_through_rest(shared_stack) -> None:
    rest, mcp = shared_stack
    created = await call_tool(
        mcp,
        "create_experiment",
        {
            **VALID_CREATE,
            "budget_amount": 15000.50,
            "currency_code": "EUR",
            "execution_steps": ["Draft variant", "Ship flag", "Measure"],
            "actual_result": "Conversion improved by 12%",
        },
    )

    response = rest.get(f"{EXPERIMENTS_URL}/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert_same_record(body, created)
    # Defaults and decimal precision survive the interface boundary.
    assert body["status"] == "draft"
    assert body["budget_amount"] == "15000.50"
    assert body["execution_steps"] == ["Draft variant", "Ship flag", "Measure"]


async def test_mcp_defaults_are_visible_through_rest(shared_stack) -> None:
    rest, mcp = shared_stack
    created = await call_tool(mcp, "create_experiment", VALID_CREATE)

    body = rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()

    assert body["status"] == "draft"
    assert body["currency_code"] == "INR"
    assert body["execution_steps"] == []
    assert body["budget_amount"] is None
    assert body["actual_result"] is None


async def test_mcp_update_is_visible_through_rest(shared_stack) -> None:
    rest, mcp = shared_stack
    created = await call_tool(mcp, "create_experiment", VALID_CREATE)

    updated = await call_tool(
        mcp,
        "update_experiment",
        {
            "experiment_id": created["id"],
            "title": "Cross-layer headline (updated)",
            "channel": "cold_email",
            "execution_steps": ["Rewrite", "Resend"],
        },
    )

    body = rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()
    assert_same_record(body, updated)
    assert body["title"] == "Cross-layer headline (updated)"
    assert body["channel"] == "cold_email"
    assert body["execution_steps"] == ["Rewrite", "Resend"]
    assert body["hypothesis"] == created["hypothesis"]


async def test_mcp_status_and_result_are_visible_through_rest(shared_stack) -> None:
    rest, mcp = shared_stack
    created = await call_tool(mcp, "create_experiment", VALID_CREATE)

    status_body = await call_tool(
        mcp,
        "update_experiment_status",
        {"experiment_id": created["id"], "status": "running"},
    )
    assert rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()["status"] == (
        "running"
    )
    assert status_body["status"] == "running"

    result_body = await call_tool(
        mcp,
        "record_experiment_result",
        {"experiment_id": created["id"], "actual_result": "Signups rose 18%"},
    )
    rest_body = rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()
    assert rest_body["actual_result"] == "Signups rose 18%"
    assert_same_record(rest_body, result_body)


async def test_mcp_delete_is_visible_through_rest(shared_stack) -> None:
    rest, mcp = shared_stack
    created = await call_tool(mcp, "create_experiment", VALID_CREATE)

    deleted = await call_tool(
        mcp, "delete_experiment", {"experiment_id": created["id"]}
    )

    assert deleted == {"deleted": True, "experiment_id": created["id"]}
    assert rest.get(f"{EXPERIMENTS_URL}/{created['id']}").status_code == 404
    listing = rest.get(EXPERIMENTS_URL).json()
    assert listing["total"] == 0
    assert listing["items"] == []


# ---------------------------------------------------------------------------
# REST -> database -> MCP
# ---------------------------------------------------------------------------


async def test_rest_create_is_visible_through_mcp(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(
        rest,
        budget_amount="1234.56",
        currency_code="USD",
        execution_steps=["Step one", "Step two"],
    )

    fetched = await call_tool(
        mcp, "get_experiment", {"experiment_id": created["id"]}
    )
    assert_same_record(created, fetched)
    assert fetched["budget_amount"] == "1234.56"

    listing = await call_tool(mcp, "list_experiments", {})
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == created["id"]


async def test_rest_update_is_visible_through_mcp(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    response = rest.patch(
        f"{EXPERIMENTS_URL}/{created['id']}",
        json={
            "title": "REST-updated headline",
            "channel": "cold_email",
            "execution_steps": ["Rewrite", "Resend"],
        },
    )
    assert response.status_code == 200, response.text

    fetched = await call_tool(
        mcp, "get_experiment", {"experiment_id": created["id"]}
    )
    assert fetched["title"] == "REST-updated headline"
    assert fetched["channel"] == "cold_email"
    assert fetched["execution_steps"] == ["Rewrite", "Resend"]
    assert fetched["hypothesis"] == created["hypothesis"]


async def test_rest_status_and_result_are_visible_through_mcp(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    status_response = rest.patch(
        f"{EXPERIMENTS_URL}/{created['id']}/status", json={"status": "completed"}
    )
    assert status_response.status_code == 200, status_response.text
    fetched = await call_tool(
        mcp, "get_experiment", {"experiment_id": created["id"]}
    )
    assert fetched["status"] == "completed"

    result_response = rest.patch(
        f"{EXPERIMENTS_URL}/{created['id']}/result",
        json={"actual_result": "REST recorded a 9% lift"},
    )
    assert result_response.status_code == 200, result_response.text
    fetched = await call_tool(
        mcp, "get_experiment", {"experiment_id": created["id"]}
    )
    assert fetched["actual_result"] == "REST recorded a 9% lift"


async def test_rest_delete_is_visible_through_mcp(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    response = rest.delete(f"{EXPERIMENTS_URL}/{created['id']}")
    assert response.status_code == 204

    missing = await mcp.call_tool(
        "get_experiment", {"experiment_id": created["id"]}
    )
    assert missing.is_error
    assert "not found" in _text(missing).lower()
    listing = await call_tool(mcp, "list_experiments", {})
    assert listing["total"] == 0


# ---------------------------------------------------------------------------
# Field and Decimal parity
# ---------------------------------------------------------------------------


async def test_field_and_decimal_parity_between_interfaces(shared_stack) -> None:
    rest, mcp = shared_stack
    created = await call_tool(
        mcp,
        "create_experiment",
        {
            **VALID_CREATE,
            "budget_amount": "9999999999.99",
            "currency_code": "INR",
            "execution_steps": ["One", "Two"],
            "actual_result": "Ten percent lift",
        },
    )

    body = rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()

    assert set(body) == set(created)
    assert isinstance(body["id"], str)
    assert uuid.UUID(body["id"])
    assert isinstance(body["execution_steps"], list)
    assert all(isinstance(step, str) for step in body["execution_steps"])
    assert isinstance(body["budget_amount"], str)
    assert Decimal(body["budget_amount"]) == Decimal("9999999999.99")
    assert body["budget_amount"] == created["budget_amount"]
    assert isinstance(body["created_at"], str)
    assert isinstance(body["updated_at"], str)
    assert_same_record(body, created)


# ---------------------------------------------------------------------------
# Duplicate operation semantics
# ---------------------------------------------------------------------------


async def test_duplicate_creates_produce_separate_records(shared_stack) -> None:
    """Creation is intentionally not idempotent: two calls mean two rows."""
    rest, mcp = shared_stack

    first = rest_create(rest)
    second = rest_create(rest)
    assert first["id"] != second["id"]
    assert rest.get(EXPERIMENTS_URL).json()["total"] == 2

    mcp_first = await call_tool(mcp, "create_experiment", VALID_CREATE)
    mcp_second = await call_tool(mcp, "create_experiment", VALID_CREATE)
    assert mcp_first["id"] != mcp_second["id"]
    assert rest.get(EXPERIMENTS_URL).json()["total"] == 4


async def test_repeated_delete_and_status_semantics(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    first = await call_tool(
        mcp, "delete_experiment", {"experiment_id": created["id"]}
    )
    assert first["deleted"] is True

    second = await mcp.call_tool(
        "delete_experiment", {"experiment_id": created["id"]}
    )
    assert second.is_error
    assert "not found" in _text(second).lower()

    # Status changes are idempotent: applying the same status twice is fine.
    created = rest_create(rest)
    for _ in range(2):
        response = rest.patch(
            f"{EXPERIMENTS_URL}/{created['id']}/status",
            json={"status": "running"},
        )
        assert response.status_code == 200, response.text
    assert rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()["status"] == (
        "running"
    )


async def test_repeated_result_is_last_write_wins(shared_stack) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    for value in ("First result", "Second result"):
        response = rest.patch(
            f"{EXPERIMENTS_URL}/{created['id']}/result",
            json={"actual_result": value},
        )
        assert response.status_code == 200, response.text

    fetched = await call_tool(
        mcp, "get_experiment", {"experiment_id": created["id"]}
    )
    assert fetched["actual_result"] == "Second result"


# ---------------------------------------------------------------------------
# Concurrency (last-write-wins, no crashes)
# ---------------------------------------------------------------------------


async def test_concurrent_cross_interface_updates_to_different_fields(
    shared_stack,
) -> None:
    rest, mcp = shared_stack
    created = rest_create(rest)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http:
        rest_response, mcp_result = await asyncio.gather(
            http.patch(
                f"{EXPERIMENTS_URL}/{created['id']}",
                json={"title": "REST title"},
            ),
            mcp.call_tool(
                "update_experiment",
                {
                    "experiment_id": created["id"],
                    "hypothesis": "MCP hypothesis",
                },
            ),
        )

    assert rest_response.status_code == 200, rest_response.text
    assert not mcp_result.is_error, _text(mcp_result)

    final = rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()
    assert final["title"] == "REST title"
    assert final["hypothesis"] == "MCP hypothesis"


async def test_concurrent_cross_interface_updates_to_same_field(
    shared_stack,
) -> None:
    """Last write wins; neither request may fail or corrupt the row."""
    rest, mcp = shared_stack
    created = rest_create(rest)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as http:
        rest_response, mcp_result = await asyncio.gather(
            http.patch(
                f"{EXPERIMENTS_URL}/{created['id']}",
                json={"title": "REST contender"},
            ),
            mcp.call_tool(
                "update_experiment",
                {
                    "experiment_id": created["id"],
                    "title": "MCP contender",
                },
            ),
        )

    assert rest_response.status_code == 200, rest_response.text
    assert not mcp_result.is_error, _text(mcp_result)

    final = rest.get(f"{EXPERIMENTS_URL}/{created['id']}").json()
    assert final["title"] in {"REST contender", "MCP contender"}
    assert final["id"] == created["id"]
