"""OAuth and MCP transport security checks that require no database."""

import base64
import hashlib
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AccessToken
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.utils import validate_authorization_response_iss

from app.core.config import get_settings
from app.main import create_app
from mcp_server.oauth import (
    ACCESS_TOKEN_TTL_SECONDS,
    CLIENT_INACTIVITY_TTL_SECONDS,
    MAX_REGISTERED_CLIENTS,
    OAUTH_REQUEST_TTL_SECONDS,
    GrowthLoopOAuthProvider,
    _BoundedRateLimiter,
)

ORIGIN = "http://localhost:5173"
ISSUER_ORIGIN = "http://localhost:8000"
RESOURCE = "http://localhost:8000/mcp"


@pytest.fixture()
def oauth_client():
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture()
def production_oauth_client(monkeypatch):
    """Exercise production consent checks without external services."""
    import app.main as main_module

    production_settings = get_settings().model_copy(update={"app_env": "production"})
    monkeypatch.setattr(main_module, "get_settings", lambda: production_settings)
    with TestClient(main_module.create_app(), base_url="https://testserver") as client:
        yield client


def _register(client: TestClient, redirect_uris: list[str], *, origin: str | None = None):
    headers = {"Origin": origin} if origin else {}
    return client.post(
        "/register",
        json={
            "client_name": "GrowthLoop OAuth security test",
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        headers=headers,
    )


def _hidden_value(body: str, name: str) -> str:
    match = re.search(
        rf'<input type="hidden" name="{re.escape(name)}" value="([^"]*)">',
        body,
    )
    assert match, f"missing hidden form value {name}"
    return match.group(1)


def _start_authorization(
    client: TestClient,
    *,
    redirect_uri: str = "http://127.0.0.1:47771/callback",
    resource: str = RESOURCE,
):
    registered = _register(client, [redirect_uri], origin=ORIGIN)
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "oauth-security-state",
            "scope": "experiments",
            "resource": resource,
        },
        follow_redirects=False,
    )
    return client_id, redirect_uri, verifier, response


def _complete_consent(
    client: TestClient, consent_location: str, *, action: str = "approve"
) -> str:
    consent_url = urlsplit(consent_location)
    request_id = parse_qs(consent_url.query)["request_id"][0]
    consent_page = client.get(f"/oauth/consent?{urlencode({'request_id': request_id})}")
    assert consent_page.status_code == 200
    nonce = _hidden_value(consent_page.text, "approval_nonce")
    login = client.post(
        f"/oauth/consent?{urlencode({'request_id': request_id})}",
        data={"approval_nonce": nonce, "password": get_settings().owner_password, "action": "login"},
        headers={"Origin": ISSUER_ORIGIN},
        follow_redirects=False,
    )
    assert login.status_code == 303
    consent_page = client.get(f"/oauth/consent?{urlencode({'request_id': request_id})}")
    assert consent_page.status_code == 200
    approve = client.post(
        f"/oauth/consent?{urlencode({'request_id': request_id})}",
        data={
            "approval_nonce": nonce,
            "csrf_token": _hidden_value(consent_page.text, "csrf_token"),
            "action": action,
        },
        headers={"Origin": ISSUER_ORIGIN},
        follow_redirects=False,
    )
    assert approve.status_code == 303
    return approve.headers["location"]


def _consent_request_id(consent_location: str) -> str:
    return parse_qs(urlsplit(consent_location).query)["request_id"][0]


def _consent_page(client: TestClient, request_id: str):
    response = client.get(
        f"/oauth/consent?{urlencode({'request_id': request_id})}"
    )
    assert response.status_code == 200
    return response


def _login_for_consent(
    client: TestClient, request_id: str, nonce: str, *, origin: str | None
):
    headers = {"Origin": origin} if origin is not None else {}
    return client.post(
        f"/oauth/consent?{urlencode({'request_id': request_id})}",
        data={
            "approval_nonce": nonce,
            "password": get_settings().owner_password,
            "action": "login",
        },
        headers=headers,
        follow_redirects=False,
    )


def _obtain_tokens(client: TestClient) -> tuple[str, str, str]:
    client_id, redirect_uri, verifier, authorize = _start_authorization(client)
    assert authorize.status_code == 302, authorize.text
    callback = _complete_consent(client, authorize.headers["location"])
    query = parse_qs(urlsplit(callback).query)
    assert query["iss"] == [get_settings().mcp_issuer_url]
    assert query["state"] == ["oauth-security-state"]
    token = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": query["code"][0],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "resource": RESOURCE,
        },
    )
    assert token.status_code == 200, token.text
    return client_id, query["code"][0], token.json()


def test_production_consent_accepts_opaque_origin_with_bound_csrf(
    production_oauth_client,
):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    assert authorize.status_code == 302
    request_id = _consent_request_id(authorize.headers["location"])
    page = _consent_page(production_oauth_client, request_id)
    nonce = _hidden_value(page.text, "approval_nonce")

    login = _login_for_consent(
        production_oauth_client, request_id, nonce, origin="null"
    )
    assert login.status_code == 303

    page = _consent_page(production_oauth_client, request_id)
    approve = production_oauth_client.post(
        f"/oauth/consent?{urlencode({'request_id': request_id})}",
        data={
            "approval_nonce": nonce,
            "csrf_token": _hidden_value(page.text, "csrf_token"),
            "action": "approve",
        },
        headers={"Origin": "null"},
        follow_redirects=False,
    )

    assert approve.status_code == 303
    query = parse_qs(urlsplit(approve.headers["location"]).query)
    assert query["state"] == ["oauth-security-state"]
    assert query["iss"] == [get_settings().mcp_issuer_url]


def test_production_consent_accepts_exact_issuer_origin(production_oauth_client):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    request_id = _consent_request_id(authorize.headers["location"])
    page = _consent_page(production_oauth_client, request_id)
    nonce = _hidden_value(page.text, "approval_nonce")
    login = _login_for_consent(
        production_oauth_client, request_id, nonce, origin=ISSUER_ORIGIN
    )
    assert login.status_code == 303

    page = _consent_page(production_oauth_client, request_id)
    approve = production_oauth_client.post(
        f"/oauth/consent?{urlencode({'request_id': request_id})}",
        data={
            "approval_nonce": nonce,
            "csrf_token": _hidden_value(page.text, "csrf_token"),
            "action": "approve",
        },
        headers={"Origin": ISSUER_ORIGIN},
        follow_redirects=False,
    )

    assert approve.status_code == 303


@pytest.mark.parametrize("origin", [ORIGIN, "https://unconfigured.example"])
def test_production_consent_rejects_disallowed_origin(
    production_oauth_client, origin
):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    request_id = _consent_request_id(authorize.headers["location"])
    page = _consent_page(production_oauth_client, request_id)
    nonce = _hidden_value(page.text, "approval_nonce")
    login = _login_for_consent(
        production_oauth_client, request_id, nonce, origin=ISSUER_ORIGIN
    )
    assert login.status_code == 303

    page = _consent_page(production_oauth_client, request_id)
    response = production_oauth_client.post(
        f"/oauth/consent?{urlencode({'request_id': request_id})}",
        data={
            "approval_nonce": nonce,
            "csrf_token": _hidden_value(page.text, "csrf_token"),
            "action": "approve",
        },
        headers={"Origin": origin},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.text == "The request origin is not allowed."


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_production_consent_requires_session_and_csrf_for_opaque_or_missing_origin(
    production_oauth_client, action
):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    request_id = _consent_request_id(authorize.headers["location"])
    page = _consent_page(production_oauth_client, request_id)
    nonce = _hidden_value(page.text, "approval_nonce")

    endpoint = f"/oauth/consent?{urlencode({'request_id': request_id})}"
    form = {"approval_nonce": nonce, "action": action}
    unauthenticated = production_oauth_client.post(
        endpoint,
        data={**form, "csrf_token": "untrusted-token"},
        headers={"Origin": "null"},
        follow_redirects=False,
    )
    assert unauthenticated.status_code == 403

    login = _login_for_consent(
        production_oauth_client, request_id, nonce, origin="null"
    )
    assert login.status_code == 303

    page = _consent_page(production_oauth_client, request_id)
    missing = production_oauth_client.post(
        endpoint, data=form, headers={"Origin": "null"}, follow_redirects=False
    )
    invalid = production_oauth_client.post(
        endpoint,
        data={**form, "csrf_token": "invalid-token"},
        headers={"Origin": "null"},
        follow_redirects=False,
    )
    non_ascii = production_oauth_client.post(
        endpoint,
        data={**form, "csrf_token": "\u2603"},
        headers={"Origin": "null"},
        follow_redirects=False,
    )
    csrf_token = _hidden_value(page.text, "csrf_token")
    missing_origin = production_oauth_client.post(
        endpoint,
        data={**form, "csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert missing.status_code == 403
    assert invalid.status_code == 403
    assert non_ascii.status_code == 403
    assert missing_origin.status_code == 303
    if action == "deny":
        assert parse_qs(urlsplit(missing_origin.headers["location"]).query)[
            "error"
        ] == ["access_denied"]


def test_consent_nonce_is_unpredictable_and_expires_with_request(
    production_oauth_client,
):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    request_id = _consent_request_id(authorize.headers["location"])
    provider = production_oauth_client.app.state.oauth_provider
    pending = provider._requests[request_id]
    nonce = pending.approval_nonce

    assert len(nonce) == 43  # secrets.token_urlsafe(32), or 256 random bits.
    assert nonce != request_id
    assert 0 < pending.expires_at - time.time() <= OAUTH_REQUEST_TTL_SECONDS
    assert provider.verify_consent_nonce(request_id, nonce)
    assert provider.complete_consent(
        request_id, f"{nonce}wrong", approved=True
    ) is None
    assert provider.verify_consent_nonce(request_id, nonce)

    provider._requests[request_id] = replace(
        pending, expires_at=time.time() - 1
    )

    assert not provider.verify_consent_nonce(request_id, nonce)
    assert provider.get_consent_request(request_id) is None
    assert provider.complete_consent(request_id, nonce, approved=True) is None


def test_consent_rejects_non_ascii_nonce_safely(production_oauth_client):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    request_id = _consent_request_id(authorize.headers["location"])
    response = production_oauth_client.post(
        f"/oauth/consent?{urlencode({'request_id': request_id})}",
        data={
            "approval_nonce": "\u2603",
            "password": "not-a-real-password",
            "action": "login",
        },
        headers={"Origin": "null"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Traceback" not in response.text


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_consent_nonce_cannot_be_replayed_after_completion(
    production_oauth_client, action
):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    request_id = _consent_request_id(authorize.headers["location"])
    page = _consent_page(production_oauth_client, request_id)
    nonce = _hidden_value(page.text, "approval_nonce")
    login = _login_for_consent(
        production_oauth_client, request_id, nonce, origin=ISSUER_ORIGIN
    )
    assert login.status_code == 303

    page = _consent_page(production_oauth_client, request_id)
    endpoint = f"/oauth/consent?{urlencode({'request_id': request_id})}"
    form = {
        "approval_nonce": nonce,
        "csrf_token": _hidden_value(page.text, "csrf_token"),
        "action": action,
    }
    first = production_oauth_client.post(
        endpoint,
        data=form,
        headers={"Origin": "null"},
        follow_redirects=False,
    )
    replay = production_oauth_client.post(
        endpoint,
        data=form,
        headers={"Origin": "null"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert replay.status_code == 400


def test_concurrent_consent_submissions_consume_request_once(
    production_oauth_client,
):
    _, _, _, authorize = _start_authorization(production_oauth_client)
    request_id = _consent_request_id(authorize.headers["location"])
    nonce = _hidden_value(
        _consent_page(production_oauth_client, request_id).text,
        "approval_nonce",
    )
    provider = production_oauth_client.app.state.oauth_provider

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda approved: provider.complete_consent(
                    request_id, nonce, approved=approved
                ),
                [True, False],
            )
        )

    assert sum(result is not None for result in results) == 1
    assert provider.get_consent_request(request_id) is None
    assert len(provider._codes) <= 1


def test_consent_nonce_is_bound_to_its_authorization_request(
    production_oauth_client,
):
    _, _, _, authorize_a = _start_authorization(production_oauth_client)
    _, _, _, authorize_b = _start_authorization(production_oauth_client)
    request_a = _consent_request_id(authorize_a.headers["location"])
    request_b = _consent_request_id(authorize_b.headers["location"])
    page_a = _consent_page(production_oauth_client, request_a)
    nonce_a = _hidden_value(page_a.text, "approval_nonce")
    login = _login_for_consent(
        production_oauth_client, request_a, nonce_a, origin=ISSUER_ORIGIN
    )
    assert login.status_code == 303

    page_b = _consent_page(production_oauth_client, request_b)
    nonce_b = _hidden_value(page_b.text, "approval_nonce")
    assert nonce_a != nonce_b
    assert len(nonce_a) == len(nonce_b) == 43
    csrf_token = _hidden_value(page_b.text, "csrf_token")
    endpoint_b = f"/oauth/consent?{urlencode({'request_id': request_b})}"
    mismatched = production_oauth_client.post(
        endpoint_b,
        data={
            "approval_nonce": nonce_a,
            "csrf_token": csrf_token,
            "action": "approve",
        },
        headers={"Origin": "null"},
        follow_redirects=False,
    )

    assert mismatched.status_code == 400
    assert production_oauth_client.app.state.oauth_provider.verify_consent_nonce(
        request_b, nonce_b
    )


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://client.example.com/oauth/callback",
        "https://localhost/oauth/callback",
    ],
)
def test_registration_accepts_https_callbacks(oauth_client, redirect_uri):
    response = _register(oauth_client, [redirect_uri])

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://localhost:43127/callback",
        "http://127.0.0.1:43127/callback",
        "http://[::1]:43127/callback",
    ],
)
def test_registration_accepts_http_loopback_callbacks(oauth_client, redirect_uri):
    response = _register(oauth_client, [redirect_uri])

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://client.example.com/callback",
        "ftp://client.example.com/callback",
        "mailto:owner@example.com",
        "https://client.example.com/callback#fragment",
        "https://user:password@client.example.com/callback",
        "https://client.example.com:invalid/callback",
        "https://client.example.com/bad%zzcallback",
        "https://client.example.com/a callback",
        "https://client.example.com\\callback",
        "https:///callback",
        "not a URI",
    ],
)
def test_registration_rejects_unsafe_or_malformed_callbacks(oauth_client, redirect_uri):
    response = _register(oauth_client, [redirect_uri])

    assert response.status_code == 400
    assert response.json()["error"] in {"invalid_redirect_uri", "invalid_client_metadata"}
    assert "Traceback" not in response.text
    assert "password@" not in response.text


def test_registration_rejects_multiple_uris_if_any_one_is_unsafe(oauth_client):
    response = _register(
        oauth_client,
        [
            "https://client.example.com/callback",
            "http://attacker.example/callback",
        ],
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_authorization_keeps_sdk_exact_redirect_uri_matching(oauth_client):
    registered_uri = "http://127.0.0.1:47771/callback"
    registered = _register(oauth_client, [registered_uri])
    assert registered.status_code == 201, registered.text
    response = oauth_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registered.json()["client_id"],
            "redirect_uri": "http://127.0.0.1:47772/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert "Location" not in response.headers


def test_authorization_rejects_wrong_resource(oauth_client):
    client_id, redirect_uri, _, response = _start_authorization(
        oauth_client, resource="https://other.example/mcp"
    )

    assert client_id
    assert redirect_uri
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == ["invalid_target"]
    assert query["iss"] == [get_settings().mcp_issuer_url]


def test_authorization_requires_resource_indicator(oauth_client):
    redirect_uri = "https://client.example.com/callback"
    registered = _register(oauth_client, [redirect_uri])
    assert registered.status_code == 201
    response = oauth_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registered.json()["client_id"],
            "redirect_uri": redirect_uri,
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == ["invalid_target"]
    assert query["iss"] == [get_settings().mcp_issuer_url]


def test_metadata_advertises_issuer_parameter_and_oauth_cors_is_exact(oauth_client):
    metadata = oauth_client.get(
        "/.well-known/oauth-authorization-server", headers={"Origin": ORIGIN}
    )

    assert metadata.status_code == 200
    assert metadata.json()["authorization_response_iss_parameter_supported"] is True
    assert metadata.headers["access-control-allow-origin"] == ORIGIN
    assert metadata.headers["access-control-allow-origin"] != "*"


def test_installed_sdk_validates_issuer_response_exactly(oauth_client):
    metadata_response = oauth_client.get("/.well-known/oauth-authorization-server")
    metadata = OAuthMetadata.model_validate(metadata_response.json())
    issuer = get_settings().mcp_issuer_url

    validate_authorization_response_iss(issuer, metadata)
    with pytest.raises(OAuthFlowError, match="iss mismatch"):
        validate_authorization_response_iss("https://wrong.example", metadata)
    with pytest.raises(OAuthFlowError, match="missing iss"):
        validate_authorization_response_iss(None, metadata)


def test_sdk_generated_authorization_error_includes_issuer(oauth_client):
    registered = _register(oauth_client, ["https://client.example.com/callback"])
    assert registered.status_code == 201
    response = oauth_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registered.json()["client_id"],
            "redirect_uri": "https://client.example.com/callback",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "scope": "unknown",
            "resource": RESOURCE,
            "state": "error-state",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["error"] == ["invalid_scope"]
    assert query["state"] == ["error-state"]
    assert query["iss"] == [get_settings().mcp_issuer_url]


def test_denial_authorization_response_includes_issuer(oauth_client):
    _, _, _, authorize = _start_authorization(oauth_client)
    callback = _complete_consent(
        oauth_client, authorize.headers["location"], action="deny"
    )
    query = parse_qs(urlsplit(callback).query)

    assert query["error"] == ["access_denied"]
    assert query["iss"] == [get_settings().mcp_issuer_url]
    assert query["state"] == ["oauth-security-state"]


@pytest.mark.anyio
async def test_code_exchange_binds_resource_and_prevents_replay(oauth_client):
    client_id, redirect_uri, verifier, authorize = _start_authorization(oauth_client)
    callback = _complete_consent(oauth_client, authorize.headers["location"])
    query = parse_qs(urlsplit(callback).query)
    code = query["code"][0]
    base_form = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    wrong_resource = oauth_client.post(
        "/token", data={**base_form, "resource": "https://other.example/mcp"}
    )
    missing_resource = oauth_client.post("/token", data=base_form)
    assert wrong_resource.status_code == 400
    assert wrong_resource.json()["error"] == "invalid_target"
    assert missing_resource.status_code == 400
    assert missing_resource.json()["error"] == "invalid_target"

    issued = oauth_client.post(
        "/token", data={**base_form, "resource": RESOURCE}
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["expires_in"] == ACCESS_TOKEN_TTL_SECONDS
    access_token = await oauth_client.app.state.oauth_provider.load_access_token(
        issued.json()["access_token"]
    )
    assert access_token.resource == RESOURCE
    replay = oauth_client.post(
        "/token", data={**base_form, "resource": RESOURCE}
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_refresh_resource_binding_rotation_and_replay(oauth_client):
    client_id, _, tokens = _obtain_tokens(oauth_client)
    base_form = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": tokens["refresh_token"],
    }
    wrong_resource = oauth_client.post(
        "/token", data={**base_form, "resource": "https://other.example/mcp"}
    )
    assert wrong_resource.status_code == 400
    assert wrong_resource.json()["error"] == "invalid_target"

    refreshed = oauth_client.post("/token", data={**base_form, "resource": RESOURCE})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]
    replay = oauth_client.post("/token", data={**base_form, "resource": RESOURCE})
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_mcp_rejects_access_token_for_another_resource(oauth_client):
    provider = oauth_client.app.state.oauth_provider
    bad_token = "wrong-resource-token"
    provider._access_tokens[provider._token_key(bad_token)] = AccessToken(
        token=bad_token,
        client_id="resource-test-client",
        scopes=["experiments"],
        expires_at=int(time.time()) + 60,
        resource="https://other.example/mcp",
    )
    response = oauth_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            "Authorization": f"Bearer {bad_token}",
            "Accept": "application/json, text/event-stream",
            "Origin": ORIGIN,
        },
    )

    assert response.status_code == 401
    assert "Traceback" not in response.text


def test_valid_oauth_token_can_list_mcp_tools_without_database(oauth_client):
    _, _, tokens = _obtain_tokens(oauth_client)
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Accept": "application/json, text/event-stream",
        "Origin": ORIGIN,
    }
    initialize = oauth_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "oauth-security-test", "version": "1"},
            },
        },
        headers=headers,
    )
    assert initialize.status_code == 200, initialize.text
    response = oauth_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert len(names) == 7


def test_registration_rate_limit_returns_safe_retry_response(oauth_client):
    for _ in range(10):
        response = _register(oauth_client, ["https://client.example.com/callback"])
        assert response.status_code == 201, response.text

    limited = _register(oauth_client, ["https://client.example.com/callback"])

    assert limited.status_code == 429
    assert limited.json() == {
        "error": "temporarily_unavailable",
        "error_description": "Too many client registrations. Try again later.",
    }
    assert limited.headers["retry-after"]
    assert "client_id" not in limited.text


def test_oauth_origin_is_restricted_and_cors_never_returns_wildcard(oauth_client):
    allowed_preflight = oauth_client.options(
        "/register",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )
    denied = _register(
        oauth_client,
        ["https://client.example.com/callback"],
        origin="https://unconfigured.example",
    )
    denied_preflight = oauth_client.options(
        "/register",
        headers={
            "Origin": "https://unconfigured.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    denied_mcp_preflight = oauth_client.options(
        "/mcp",
        headers={
            "Origin": "https://unconfigured.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )

    assert allowed_preflight.status_code == 200
    assert allowed_preflight.headers["access-control-allow-origin"] == ORIGIN
    assert "authorization" in allowed_preflight.headers["access-control-allow-headers"].lower()
    assert denied.status_code == 403
    assert "access-control-allow-origin" not in denied.headers
    assert denied_preflight.status_code == 403
    assert "access-control-allow-origin" not in denied_preflight.headers
    assert denied_mcp_preflight.status_code == 403
    assert "access-control-allow-origin" not in denied_mcp_preflight.headers


def test_host_and_mcp_origin_are_rejected_by_their_transport_layers(oauth_client):
    _, _, tokens = _obtain_tokens(oauth_client)
    bearer = f"Bearer {tokens['access_token']}"
    host_response = oauth_client.get(
        "/.well-known/oauth-authorization-server",
        headers={"Host": "unlisted.example"},
    )
    mcp_response = oauth_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            "Origin": "https://unlisted.example",
            "Authorization": bearer,
            "Accept": "application/json, text/event-stream",
        },
    )
    sdk_host_response = oauth_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            "Host": "testserver:9999",
            "Origin": ORIGIN,
            "Authorization": bearer,
            "Accept": "application/json, text/event-stream",
        },
    )

    assert host_response.status_code == 400
    assert mcp_response.status_code == 403
    assert sdk_host_response.status_code == 421
    assert "Traceback" not in host_response.text + mcp_response.text + sdk_host_response.text


@pytest.mark.anyio
async def test_expired_client_registration_is_removed_before_capacity_check():
    provider = GrowthLoopOAuthProvider("http://localhost:8000", RESOURCE)
    old = OAuthClientInformationFull.model_validate(
        {
            "client_id": "old-client",
            "redirect_uris": ["https://old.example/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
    )
    new = old.model_copy(update={"client_id": "new-client"})
    await provider.register_client(old)
    provider._client_last_seen[old.client_id] = (
        time.time() - CLIENT_INACTIVITY_TTL_SECONDS - 1
    )

    await provider.register_client(new)

    assert await provider.get_client(old.client_id) is None
    assert await provider.get_client(new.client_id) is not None
    assert len(provider._clients) <= MAX_REGISTERED_CLIENTS


def test_rate_limit_bucket_count_is_hard_bounded():
    limiter = _BoundedRateLimiter(limit=1, window_seconds=60, max_keys=2)

    assert limiter.allow("client-a", now=10)
    assert limiter.allow("client-b", now=10)
    assert not limiter.allow("client-c", now=10)
    assert len(limiter._attempts) == 2
