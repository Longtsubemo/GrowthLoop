"""Integration tests for the GrowthLoop MCP server.

Every test drives the real MCP stack: an SDK client session connected to
the server through the SDK's in-memory transport (full JSON-RPC framing
plus the initialize handshake), with the server's session factory pointed
at the isolated throwaway database. The final test spawns the server as
a real subprocess and speaks stdio.

These are not unit tests of the handler functions — tools are only ever
invoked through ``ClientSession``-backed ``Client.call_tool`` round
trips, so argument validation, error translation and result conversion
are exercised exactly as a remote Claude client would see them.
"""

import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from mcp import Client, StdioServerParameters
from sqlalchemy.orm import sessionmaker

from app.models import Experiment
from mcp_server import server as mcp_server_module

BACKEND_DIR = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.anyio

EXPECTED_TOOLS = {
    "create_experiment",
    "list_experiments",
    "get_experiment",
    "update_experiment",
    "update_experiment_status",
    "record_experiment_result",
    "delete_experiment",
}

VALID_CREATE: dict[str, object] = {
    "title": "Landing page headline test",
    "hypothesis": "A benefit-led headline increases signups",
    "target_audience": "First-time visitors from Product Hunt",
    "channel": "landing_page",
    "success_metric": "Signup conversion rate",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mcp_db(migrated_engine, monkeypatch):
    """Point the server's session factory at the throwaway database.

    The monkeypatch is undone after each test; leftover rows are removed
    so every test starts from an empty ``experiments`` table.
    """
    factory = sessionmaker(bind=migrated_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(mcp_server_module, "SessionLocal", factory)
    yield migrated_engine
    with migrated_engine.begin() as connection:
        connection.execute(sa.delete(Experiment))


@pytest.fixture()
async def client(mcp_db):
    """An MCP client connected over the in-memory JSON-RPC transport."""
    async with Client(mcp_server_module.mcp, mode="legacy") as connected:
        yield connected


async def tool_create(client: Client, **overrides: object) -> dict:
    """Create a valid experiment through the MCP tool and return it."""
    result = await client.call_tool(
        "create_experiment", {**VALID_CREATE, **overrides}
    )
    assert not result.is_error, _text(result)
    return result.structured_content


def _text(result) -> str:
    """The first text block of a (usually error) tool result."""
    return result.content[0].text if result.content else ""


# ---------------------------------------------------------------------------
# Discovery, connection and schemas
# ---------------------------------------------------------------------------


async def test_client_initializes_and_connects(client: Client) -> None:
    # Entering the client fixture completed the initialize handshake.
    assert client.session is not None
    assert client.protocol_version


async def test_all_seven_tools_discoverable(client: Client) -> None:
    result = await client.list_tools()

    assert {tool.name for tool in result.tools} == EXPECTED_TOOLS


async def test_tool_input_schemas_are_accurate(client: Client) -> None:
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    create = tools["create_experiment"].input_schema
    assert create["type"] == "object"
    assert set(create["required"]) == {
        "title",
        "hypothesis",
        "target_audience",
        "channel",
        "success_metric",
    }
    properties = create["properties"]
    assert properties["title"] == {
        **properties["title"],
        "type": "string",
        "minLength": 1,
        "maxLength": 200,
    }
    assert properties["currency_code"]["pattern"] == "^[A-Z]{3}$"
    assert properties["currency_code"]["default"] == "INR"
    assert properties["status"]["default"] == "draft"
    assert set(create["$defs"]["ExperimentStatus"]["enum"]) == {
        "draft",
        "planned",
        "running",
        "completed",
        "paused",
        "cancelled",
    }

    update = tools["update_experiment"].input_schema
    assert update["required"] == ["experiment_id"]
    assert "budget_amount" in update["properties"]
    # No default is advertised for sentinel-guarded optional fields.
    assert "default" not in update["properties"]["title"]

    listing = tools["list_experiments"].input_schema
    assert listing["properties"]["limit"]["default"] == 20
    assert listing["properties"]["limit"]["maximum"] == 100
    assert listing["properties"]["offset"]["minimum"] == 0

    for tool in tools.values():
        assert tool.description, tool.name


async def test_tool_annotations(client: Client) -> None:
    tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert tools["get_experiment"].annotations.read_only_hint is True
    assert tools["list_experiments"].annotations.read_only_hint is True
    assert tools["delete_experiment"].annotations.destructive_hint is True
    delete_description = tools["delete_experiment"].description.lower()
    assert "delete" in delete_description
    assert "cannot be recovered" in delete_description


# ---------------------------------------------------------------------------
# create_experiment
# ---------------------------------------------------------------------------


async def test_create_returns_stored_experiment(client: Client) -> None:
    experiment = await tool_create(
        client,
        budget_amount=15000.50,
        currency_code="EUR",
        status="running",
        execution_steps=["Draft variant", "Ship flag", "Measure"],
        actual_result="Conversion improved by 12%",
    )

    assert uuid.UUID(experiment["id"])
    assert experiment["title"] == VALID_CREATE["title"]
    assert experiment["hypothesis"] == VALID_CREATE["hypothesis"]
    assert experiment["target_audience"] == VALID_CREATE["target_audience"]
    assert experiment["channel"] == VALID_CREATE["channel"]
    assert experiment["budget_amount"] == "15000.50"
    assert experiment["currency_code"] == "EUR"
    assert experiment["status"] == "running"
    assert experiment["execution_steps"] == ["Draft variant", "Ship flag", "Measure"]
    assert experiment["success_metric"] == VALID_CREATE["success_metric"]
    assert experiment["actual_result"] == "Conversion improved by 12%"
    assert experiment["created_at"]
    assert experiment["updated_at"]


async def test_create_applies_defaults(client: Client) -> None:
    experiment = await tool_create(client)

    assert experiment["status"] == "draft"
    assert experiment["currency_code"] == "INR"
    assert experiment["execution_steps"] == []
    assert experiment["budget_amount"] is None
    assert experiment["actual_result"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "x" * 201},
        {"channel": "x" * 51},
        {"hypothesis": "   "},
        {"currency_code": "inr"},
        {"status": "bogus"},
        {"budget_amount": -10},
        {"execution_steps": ["ok", ""]},
    ],
)
async def test_create_rejects_invalid_payload(
    client: Client, overrides: dict
) -> None:
    result = await client.call_tool(
        "create_experiment", {**VALID_CREATE, **overrides}
    )

    assert result.is_error
    text = _text(result)
    assert "Traceback" not in text
    assert "sqlalchemy" not in text.lower()
    assert "postgres" not in text.lower()


async def test_create_rejects_missing_required_field(client: Client) -> None:
    payload = {k: v for k, v in VALID_CREATE.items() if k != "success_metric"}

    result = await client.call_tool("create_experiment", payload)

    assert result.is_error
    assert "success_metric" in _text(result)


# ---------------------------------------------------------------------------
# get_experiment
# ---------------------------------------------------------------------------


async def test_get_returns_existing_experiment(client: Client) -> None:
    created = await tool_create(client, budget_amount=2500)

    result = await client.call_tool(
        "get_experiment", {"experiment_id": created["id"]}
    )

    assert not result.is_error
    experiment = result.structured_content
    assert experiment["id"] == created["id"]
    assert experiment["title"] == created["title"]
    assert experiment["budget_amount"] == "2500.00"


async def test_get_unknown_experiment_is_clean_error(client: Client) -> None:
    missing = str(uuid.uuid4())

    result = await client.call_tool("get_experiment", {"experiment_id": missing})

    assert result.is_error
    text = _text(result)
    assert missing in text
    assert "not found" in text.lower()


async def test_get_invalid_uuid_is_clean_error(client: Client) -> None:
    result = await client.call_tool(
        "get_experiment", {"experiment_id": "not-a-uuid"}
    )

    assert result.is_error
    assert "uuid" in _text(result).lower()


# ---------------------------------------------------------------------------
# list_experiments
# ---------------------------------------------------------------------------


async def test_list_returns_newest_first_with_totals(client: Client) -> None:
    first = await tool_create(client, title="First")
    second = await tool_create(client, title="Second")
    third = await tool_create(client, title="Third")

    result = await client.call_tool("list_experiments", {})

    assert not result.is_error
    body = result.structured_content
    assert body["total"] == 3
    assert [item["title"] for item in body["items"]] == [
        third["title"],
        second["title"],
        first["title"],
    ]
    assert body["limit"] == 20
    assert body["offset"] == 0


async def test_list_paginates(client: Client) -> None:
    created = [await tool_create(client, title=f"Exp {i}") for i in range(5)]

    page_one = await client.call_tool("list_experiments", {"limit": 2})
    body = page_one.structured_content
    assert body["total"] == 5
    assert [item["title"] for item in body["items"]] == [
        created[4]["title"],
        created[3]["title"],
    ]

    page_two = await client.call_tool(
        "list_experiments", {"limit": 2, "offset": 2}
    )
    assert [item["title"] for item in page_two.structured_content["items"]] == [
        created[2]["title"],
        created[1]["title"],
    ]

    beyond = await client.call_tool(
        "list_experiments", {"limit": 2, "offset": 6}
    )
    assert beyond.structured_content["items"] == []


async def test_list_filters_by_status(client: Client) -> None:
    await tool_create(client, title="Draft one")
    await tool_create(client, title="Running one", status="running")
    await tool_create(client, title="Running two", status="running")

    result = await client.call_tool("list_experiments", {"status": "running"})

    body = result.structured_content
    assert body["total"] == 2
    assert {item["title"] for item in body["items"]} == {
        "Running one",
        "Running two",
    }


@pytest.mark.parametrize(
    "arguments",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "bogus"}],
)
async def test_list_rejects_invalid_arguments(
    client: Client, arguments: dict
) -> None:
    result = await client.call_tool("list_experiments", arguments)

    assert result.is_error
    assert "Traceback" not in _text(result)


async def test_list_returns_empty_result(client: Client) -> None:
    result = await client.call_tool("list_experiments", {})

    assert not result.is_error
    assert result.structured_content == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }


# ---------------------------------------------------------------------------
# update_experiment
# ---------------------------------------------------------------------------


async def test_update_single_field_leaves_others_unchanged(
    client: Client,
) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "update_experiment",
        {"experiment_id": created["id"], "title": "New headline"},
    )

    assert not result.is_error
    experiment = result.structured_content
    assert experiment["title"] == "New headline"
    assert experiment["hypothesis"] == created["hypothesis"]
    assert experiment["channel"] == created["channel"]
    assert experiment["success_metric"] == created["success_metric"]
    assert experiment["status"] == "draft"
    assert experiment["updated_at"] > created["updated_at"]
    assert experiment["created_at"] == created["created_at"]


async def test_update_multiple_fields_together(client: Client) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "update_experiment",
        {
            "experiment_id": created["id"],
            "title": "New headline",
            "channel": "cold_email",
            "execution_steps": ["Rewrite", "Resend"],
        },
    )

    experiment = result.structured_content
    assert experiment["title"] == "New headline"
    assert experiment["channel"] == "cold_email"
    assert experiment["execution_steps"] == ["Rewrite", "Resend"]
    assert experiment["hypothesis"] == created["hypothesis"]


async def test_update_explicit_null_clears_optional_fields(
    client: Client,
) -> None:
    created = await tool_create(
        client, budget_amount=5000, actual_result="Improved 5%"
    )

    result = await client.call_tool(
        "update_experiment",
        {
            "experiment_id": created["id"],
            "budget_amount": None,
            "actual_result": None,
        },
    )

    assert not result.is_error
    experiment = result.structured_content
    assert experiment["budget_amount"] is None
    assert experiment["actual_result"] is None


async def test_update_explicit_null_on_required_field_rejected(
    client: Client,
) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "update_experiment", {"experiment_id": created["id"], "title": None}
    )

    assert result.is_error
    assert "title" in _text(result)
    # The stored experiment is untouched.
    stored = await client.call_tool(
        "get_experiment", {"experiment_id": created["id"]}
    )
    assert stored.structured_content["title"] == created["title"]


async def test_update_rejects_invalid_values(client: Client) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "update_experiment", {"experiment_id": created["id"], "budget_amount": -5}
    )

    assert result.is_error


async def test_update_unknown_experiment_is_clean_error(client: Client) -> None:
    missing = str(uuid.uuid4())

    result = await client.call_tool(
        "update_experiment", {"experiment_id": missing, "title": "New headline"}
    )

    assert result.is_error
    assert "not found" in _text(result).lower()


async def test_update_invalid_uuid_is_clean_error(client: Client) -> None:
    result = await client.call_tool(
        "update_experiment", {"experiment_id": "not-a-uuid", "title": "New headline"}
    )

    assert result.is_error


# ---------------------------------------------------------------------------
# update_experiment_status
# ---------------------------------------------------------------------------


async def test_update_experiment_status(client: Client) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "update_experiment_status",
        {"experiment_id": created["id"], "status": "running"},
    )

    assert not result.is_error
    experiment = result.structured_content
    assert experiment["status"] == "running"
    assert experiment["updated_at"] > created["updated_at"]


async def test_update_status_rejects_invalid_value(client: Client) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "update_experiment_status",
        {"experiment_id": created["id"], "status": "bogus"},
    )

    assert result.is_error


async def test_update_status_unknown_experiment(client: Client) -> None:
    result = await client.call_tool(
        "update_experiment_status",
        {"experiment_id": str(uuid.uuid4()), "status": "running"},
    )

    assert result.is_error
    assert "not found" in _text(result).lower()


# ---------------------------------------------------------------------------
# record_experiment_result
# ---------------------------------------------------------------------------


async def test_record_experiment_result(client: Client) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "record_experiment_result",
        {"experiment_id": created["id"], "actual_result": "Signups improved 12%"},
    )

    assert not result.is_error
    experiment = result.structured_content
    assert experiment["actual_result"] == "Signups improved 12%"
    assert experiment["status"] == "draft"


async def test_record_result_rejects_empty_text(client: Client) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "record_experiment_result",
        {"experiment_id": created["id"], "actual_result": "   "},
    )

    assert result.is_error


async def test_record_result_unknown_experiment(client: Client) -> None:
    result = await client.call_tool(
        "record_experiment_result",
        {"experiment_id": str(uuid.uuid4()), "actual_result": "Anything"},
    )

    assert result.is_error
    assert "not found" in _text(result).lower()


# ---------------------------------------------------------------------------
# delete_experiment
# ---------------------------------------------------------------------------


async def test_delete_removes_experiment(client: Client) -> None:
    created = await tool_create(client)

    result = await client.call_tool(
        "delete_experiment", {"experiment_id": created["id"]}
    )

    assert not result.is_error
    assert result.structured_content == {
        "deleted": True,
        "experiment_id": created["id"],
    }

    gone = await client.call_tool(
        "get_experiment", {"experiment_id": created["id"]}
    )
    assert gone.is_error
    listing = await client.call_tool("list_experiments", {})
    assert listing.structured_content["total"] == 0


async def test_delete_unknown_experiment_is_clean_error(client: Client) -> None:
    result = await client.call_tool(
        "delete_experiment", {"experiment_id": str(uuid.uuid4())}
    )

    assert result.is_error
    assert "not found" in _text(result).lower()


async def test_delete_invalid_uuid_is_clean_error(client: Client) -> None:
    result = await client.call_tool("delete_experiment", {"experiment_id": "nope"})

    assert result.is_error


# ---------------------------------------------------------------------------
# Robustness and persistence
# ---------------------------------------------------------------------------


async def test_server_remains_usable_after_invalid_requests(
    client: Client,
) -> None:
    invalid_calls = [
        ("get_experiment", {"experiment_id": "not-a-uuid"}),
        ("get_experiment", {}),
        ("get_experiment", {"experiment_id": str(uuid.uuid4())}),
        ("create_experiment", {"title": ""}),
        ("update_experiment_status", {"experiment_id": "bad", "status": "running"}),
        ("record_experiment_result", {"experiment_id": "bad", "actual_result": "x"}),
        ("delete_experiment", {"experiment_id": "bad"}),
    ]
    for name, arguments in invalid_calls:
        result = await client.call_tool(name, arguments)
        assert result.is_error, name

    created = await tool_create(client, title="Still alive")
    fetched = await client.call_tool(
        "get_experiment", {"experiment_id": created["id"]}
    )
    assert not fetched.is_error
    assert fetched.structured_content["title"] == "Still alive"


async def test_changes_persist_across_connections_and_sessions(mcp_db) -> None:
    async with Client(mcp_server_module.mcp, mode="legacy") as first:
        created = await tool_create(first, title="Persistent")

    # A brand-new MCP connection — and therefore new database sessions
    # for every tool call — must see the same row.
    async with Client(mcp_server_module.mcp, mode="legacy") as second:
        fetched = await second.call_tool(
            "get_experiment", {"experiment_id": created["id"]}
        )
        assert not fetched.is_error
        assert fetched.structured_content["title"] == "Persistent"

    # And directly through a fresh SQLAlchemy session, bypassing MCP.
    factory = sessionmaker(bind=mcp_db)
    with factory() as session:
        stored = session.get(Experiment, uuid.UUID(created["id"]))
        assert stored is not None
        assert stored.title == "Persistent"


# ---------------------------------------------------------------------------
# Real stdio transport: spawn the server as a subprocess
# ---------------------------------------------------------------------------


async def test_stdio_subprocess_smoke(mcp_db) -> None:
    """Spawn the real server process and drive it over the stdio wire."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(BACKEND_DIR),
        # str(engine.url) masks the password as ***; render it in full so
        # the subprocess connects to the throwaway database.
        env={"DATABASE_URL": mcp_db.url.render_as_string(hide_password=False)},
    )
    async with Client(parameters, read_timeout_seconds=60) as remote:
        tools = await remote.list_tools()
        assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS

        created = await remote.call_tool("create_experiment", VALID_CREATE)
        assert not created.is_error
        experiment_id = created.structured_content["id"]
        assert created.structured_content["status"] == "draft"

        fetched = await remote.call_tool(
            "get_experiment", {"experiment_id": experiment_id}
        )
        assert not fetched.is_error
        assert fetched.structured_content["title"] == VALID_CREATE["title"]

        listed = await remote.call_tool("list_experiments", {})
        assert listed.structured_content["total"] == 1

        updated = await remote.call_tool(
            "update_experiment_status",
            {"experiment_id": experiment_id, "status": "running"},
        )
        assert not updated.is_error
        assert updated.structured_content["status"] == "running"

        deleted = await remote.call_tool(
            "delete_experiment", {"experiment_id": experiment_id}
        )
        assert not deleted.is_error
        assert deleted.structured_content["deleted"] is True

        missing = await remote.call_tool(
            "get_experiment", {"experiment_id": experiment_id}
        )
        assert missing.is_error
        assert "not found" in _text(missing).lower()
