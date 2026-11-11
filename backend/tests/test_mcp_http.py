"""Streamable HTTP integration tests for the hosted MCP endpoint."""

import json
import base64
import hashlib
import secrets
from collections.abc import Iterator
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db_session
from app.core.config import get_settings
from app.main import app
from app.models import Experiment
from mcp_server import server as mcp_server_module

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

REQUEST_HEADERS = {
    "accept": "application/json, text/event-stream",
    "origin": "http://localhost:5173",
}


@pytest.fixture()
def mcp_http_client(api_client, migrated_engine, monkeypatch):
    """Use the normal API test client with MCP on the same isolated DB."""
    factory = sessionmaker(bind=migrated_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(mcp_server_module, "SessionLocal", factory)
    api_client.headers["Authorization"] = f"Bearer {_oauth_access_token(api_client)}"
    return api_client


def _post_rpc(
    client: TestClient,
    method: str,
    params: dict | None = None,
    *,
    request_id: int | None = 1,
    headers: dict[str, str] | None = None,
):
    payload: dict = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params
    response = client.post(
        "/mcp",
        json=payload,
        headers={**REQUEST_HEADERS, **(headers or {})},
    )
    return response


def _initialize(client: TestClient) -> None:
    response = _post_rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "growthloop-http-tests", "version": "1.0"},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["protocolVersion"]
    notification = _post_rpc(
        client,
        "notifications/initialized",
        request_id=None,
    )
    assert notification.status_code in {200, 202, 204}, notification.text


def _oauth_access_token(client: TestClient) -> str:
    """Complete the SDK OAuth authorization-code and PKCE flow in-process."""
    redirect_uri = "http://127.0.0.1:47771/callback"
    registered = client.post(
        "/register",
        json={
            "client_name": "GrowthLoop HTTP tests",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    resource_url = "http://localhost:8000/mcp"
    authorize = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "test-oauth-state",
            "scope": "experiments",
            "resource": resource_url,
        },
        follow_redirects=False,
    )
    assert authorize.status_code == 302, authorize.text
    consent_location = urlsplit(authorize.headers["location"])
    consent_path = consent_location.path + "?" + consent_location.query
    consent_page = client.get(consent_path)
    assert consent_page.status_code == 200, consent_page.text
    nonce = _form_value(consent_page.text, "approval_nonce")
    csrf_token = _form_value(consent_page.text, "csrf_token")
    consent_request_id = parse_qs(consent_location.query)["request_id"][0]
    approved = client.post(
        f"/oauth/consent?{urlencode({'request_id': consent_request_id})}",
        data={
            "approval_nonce": nonce,
            "csrf_token": csrf_token,
            "action": "approve",
        },
        headers={"origin": "http://localhost:5173"},
        follow_redirects=False,
    )
    assert approved.status_code == 303, approved.text
    code = parse_qs(urlsplit(approved.headers["location"]).query)["code"][0]
    token_response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "resource": resource_url,
        },
    )
    assert token_response.status_code == 200, token_response.text
    return token_response.json()["access_token"]


def _form_value(body: str, name: str) -> str:
    import re

    match = re.search(
        rf'<input type="hidden" name="{re.escape(name)}" value="([^"]*)">',
        body,
    )
    assert match, body
    return match.group(1)


def _tool_call(client: TestClient, name: str, arguments: dict, request_id: int = 2):
    response = _post_rpc(
        client,
        "tools/call",
        {"name": name, "arguments": arguments},
        request_id=request_id,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    result = body["result"]
    if "structuredContent" in result:
        return result["structuredContent"]
    text_blocks = [item["text"] for item in result.get("content", []) if "text" in item]
    assert text_blocks, result
    return json.loads(text_blocks[0])


async def test_streamable_http_initializes_and_lists_seven_tools(
    mcp_http_client: TestClient,
) -> None:
    _initialize(mcp_http_client)

    response = _post_rpc(mcp_http_client, "tools/list", {}, request_id=2)

    assert response.status_code == 200, response.text
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == EXPECTED_TOOLS


async def test_http_create_is_visible_through_rest(
    mcp_http_client: TestClient,
) -> None:
    _initialize(mcp_http_client)
    created = _tool_call(mcp_http_client, "create_experiment", VALID_CREATE)

    response = mcp_http_client.get(f"/api/v1/experiments/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["title"] == VALID_CREATE["title"]


async def test_http_status_and_result_updates_are_visible_through_rest(
    mcp_http_client: TestClient,
) -> None:
    _initialize(mcp_http_client)
    created = _tool_call(mcp_http_client, "create_experiment", VALID_CREATE)
    experiment_id = created["id"]

    updated = _tool_call(
        mcp_http_client,
        "update_experiment_status",
        {"experiment_id": experiment_id, "status": "running"},
    )
    assert mcp_http_client.get(
        f"/api/v1/experiments/{experiment_id}"
    ).json()["status"] == "running"
    assert updated["status"] == "running"

    result = _tool_call(
        mcp_http_client,
        "record_experiment_result",
        {
            "experiment_id": experiment_id,
            "actual_result": "Conversion improved by 12%",
        },
    )
    assert mcp_http_client.get(
        f"/api/v1/experiments/{experiment_id}"
    ).json()["actual_result"] == "Conversion improved by 12%"
    assert result["actual_result"] == "Conversion improved by 12%"


async def test_http_delete_is_visible_through_rest(
    mcp_http_client: TestClient,
) -> None:
    _initialize(mcp_http_client)
    created = _tool_call(mcp_http_client, "create_experiment", VALID_CREATE)

    deleted = _tool_call(
        mcp_http_client,
        "delete_experiment",
        {"experiment_id": created["id"]},
    )

    assert deleted["deleted"] is True
    assert mcp_http_client.get(
        f"/api/v1/experiments/{created['id']}"
    ).status_code == 404


async def test_all_seven_tools_work_with_oauth_bearer_token(
    mcp_http_client: TestClient,
) -> None:
    _initialize(mcp_http_client)
    created = _tool_call(mcp_http_client, "create_experiment", VALID_CREATE)
    experiment_id = created["id"]

    listed = _tool_call(mcp_http_client, "list_experiments", {})
    assert any(item["id"] == experiment_id for item in listed["items"])
    fetched = _tool_call(
        mcp_http_client,
        "get_experiment",
        {"experiment_id": experiment_id},
    )
    assert fetched["id"] == experiment_id
    updated = _tool_call(
        mcp_http_client,
        "update_experiment",
        {"experiment_id": experiment_id, "title": "Updated through OAuth"},
    )
    assert updated["title"] == "Updated through OAuth"
    status = _tool_call(
        mcp_http_client,
        "update_experiment_status",
        {"experiment_id": experiment_id, "status": "running"},
    )
    assert status["status"] == "running"
    result = _tool_call(
        mcp_http_client,
        "record_experiment_result",
        {"experiment_id": experiment_id, "actual_result": "Lift was 8%"},
    )
    assert result["actual_result"] == "Lift was 8%"
    deleted = _tool_call(
        mcp_http_client,
        "delete_experiment",
        {"experiment_id": experiment_id},
    )
    assert deleted["deleted"] is True


async def test_invalid_http_requests_return_safe_errors(
    mcp_http_client: TestClient,
) -> None:
    _initialize(mcp_http_client)
    invalid_call = _post_rpc(
        mcp_http_client,
        "tools/call",
        {"name": "missing_tool", "arguments": {}},
        request_id=2,
    )
    malformed = mcp_http_client.post(
        "/mcp",
        content="{not-json",
        headers={**REQUEST_HEADERS, "content-type": "application/json"},
    )

    assert invalid_call.status_code == 200
    assert invalid_call.json().get("error") or invalid_call.json().get("result", {}).get(
        "isError"
    )
    assert malformed.status_code in {400, 415}
    assert "Traceback" not in invalid_call.text + malformed.text
    assert "secret-value" not in invalid_call.text + malformed.text


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({"host": "unlisted.example.com"}, 400),
        ({"origin": "https://unlisted.example.com"}, 403),
    ],
)
async def test_http_transport_rejects_unlisted_host_and_origin(
    mcp_http_client: TestClient, headers: dict[str, str], expected_status: int
) -> None:
    response = _post_rpc(
        mcp_http_client,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "security-test", "version": "1"},
        },
        headers=headers,
    )

    assert response.status_code == expected_status
    assert "Traceback" not in response.text


async def test_session_manager_starts_stops_and_is_recreated(
    migrated_engine, monkeypatch
) -> None:
    factory = sessionmaker(bind=migrated_engine, autoflush=False, autocommit=False)

    def override_get_db_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    monkeypatch.setattr(mcp_server_module, "SessionLocal", factory)
    app.dependency_overrides[get_db_session] = override_get_db_session
    managers = []
    try:
        for _ in range(2):
            with TestClient(app) as client:
                login = client.post(
                    "/api/v1/auth/login",
                    json={"password": get_settings().owner_password},
                    headers={"Origin": "http://localhost:5173"},
                )
                assert login.status_code == 200, login.text
                manager = app.state.mcp_session_manager
                managers.append(manager)
                assert manager._task_group is not None
                client.headers["Authorization"] = f"Bearer {_oauth_access_token(client)}"
                _initialize(client)
            assert manager._task_group is None
            assert client.post("/mcp", json={}).status_code == 503
    finally:
        app.dependency_overrides.clear()
        with migrated_engine.begin() as connection:
            connection.execute(Experiment.__table__.delete())

    assert managers[0] is not managers[1]
