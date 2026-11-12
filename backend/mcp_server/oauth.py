"""Application-managed OAuth provider for Claude's remote MCP connector."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.core.auth import (
    InvalidOwnerPassword,
    LoginRateLimited,
    OwnerAuthService,
    SESSION_COOKIE_NAME,
)

OAUTH_SCOPE = "experiments"
logger = logging.getLogger(__name__)
ACCESS_TOKEN_TTL_SECONDS = 900
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
AUTHORIZATION_CODE_TTL_SECONDS = 180
OAUTH_REQUEST_TTL_SECONDS = 600
CLIENT_INACTIVITY_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_REGISTERED_CLIENTS = 512
MAX_PENDING_AUTHORIZATIONS = 256
MAX_AUTHORIZATION_CODES = 512
MAX_ACTIVE_TOKEN_PAIRS = 2048
DCR_RATE_LIMIT_WINDOW_SECONDS = 60 * 60
DCR_RATE_LIMIT_REQUESTS = 10
MAX_DCR_RATE_LIMIT_KEYS = 2048
MAX_TOKEN_REQUEST_BODY_BYTES = 64 * 1024
MAX_DIAGNOSTIC_BODY_BYTES = 64 * 1024
MAX_DIAGNOSTIC_RESPONSE_BYTES = 8 * 1024
_TOKEN_ERROR_CATEGORIES = frozenset(
    {
        "invalid_request",
        "invalid_client",
        "invalid_grant",
        "unauthorized_client",
        "unsupported_grant_type",
        "invalid_scope",
        "invalid_target",
        "temporarily_unavailable",
        "server_error",
    }
)
_MCP_INITIALIZATION_METHODS = frozenset({"initialize", "server/discover"})
_OAUTH_ENDPOINTS = {
    "/authorize",
    "/register",
    "/token",
    "/revoke",
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
    "/.well-known/oauth-protected-resource/mcp",
}
_ORIGIN_GUARDED_PATHS = _OAUTH_ENDPOINTS | {"/mcp"}
_CONSENT_SUBMIT_SCRIPT = """(() => {
  const form = document.querySelector('form[data-consent-form]');
  if (!form) return;
  form.addEventListener('submit', (event) => {
    if (form.dataset.submitted === 'true') {
      event.preventDefault();
      return;
    }
    form.dataset.submitted = 'true';
    const submitter = event.submitter;
    if (submitter && submitter.name === 'action') {
      const action = document.createElement('input');
      action.type = 'hidden';
      action.name = 'action';
      action.value = submitter.value;
      form.appendChild(action);
      submitter.removeAttribute('name');
    }
    form.querySelectorAll('button[type="submit"]').forEach((button) => {
      button.disabled = true;
    });
  });
})();"""
_CONSENT_SUBMIT_SCRIPT_HASH = base64.b64encode(
    hashlib.sha256(_CONSENT_SUBMIT_SCRIPT.encode("utf-8")).digest()
).decode("ascii")


def _is_safe_redirect_uri(uri: str) -> bool:
    """Accept HTTPS callbacks and HTTP callbacks bound to loopback only."""
    if (
        not uri
        or uri != uri.strip()
        or "\\" in uri
        or any(ord(char) <= 0x20 for char in uri)
        or re.search(r"%(?![0-9A-Fa-f]{2})", uri) is not None
    ):
        return False
    try:
        parsed = urlsplit(uri)
        hostname = parsed.hostname
        # Accessing ``port`` validates malformed and out-of-range ports.
        _ = parsed.port
    except ValueError:
        return False
    if (
        not parsed.scheme
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "#" in uri
    ):
        return False
    if parsed.scheme.lower() == "https":
        return True
    if parsed.scheme.lower() != "http":
        return False
    if hostname.lower() == "localhost":
        return True
    if "%" in hostname:
        return False
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class _BoundedRateLimiter:
    """Small process-local sliding-window limiter with a hard key bound."""

    def __init__(
        self,
        *,
        limit: int = DCR_RATE_LIMIT_REQUESTS,
        window_seconds: int = DCR_RATE_LIMIT_WINDOW_SECONDS,
        max_keys: int = MAX_DCR_RATE_LIMIT_KEYS,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self.window_seconds
        with self._lock:
            attempts = self._attempts.get(key)
            if attempts is None:
                # Stale keys are cheap to prune and cannot consume unbounded memory.
                for stale_key, stale_attempts in list(self._attempts.items()):
                    while stale_attempts and stale_attempts[0] <= cutoff:
                        stale_attempts.popleft()
                    if not stale_attempts:
                        self._attempts.pop(stale_key, None)
                if len(self._attempts) >= self.max_keys:
                    return False
                attempts = deque()
                self._attempts[key] = attempts
            else:
                self._attempts.move_to_end(key)
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
            if len(attempts) >= self.limit:
                return False
            attempts.append(timestamp)
            return True


class OAuthCorsPreflightGuardMiddleware:
    """Keep MCP and OAuth preflights within the exact MCP origin allowlist."""

    _GUARDED_PATHS = _ORIGIN_GUARDED_PATHS

    def __init__(self, app, *, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        origin = headers.get(b"origin")
        if (
            scope.get("method", "").upper() == "OPTIONS"
            and scope.get("path", "") in self._GUARDED_PATHS
            and headers.get(b"access-control-request-method")
            and origin
            and origin.decode("latin-1") not in self.allowed_origins
        ):
            body = b'{"detail":"Request origin is not allowed."}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return
        await self.app(scope, receive, send)


def _token_failure_category(body: bytes, *, truncated: bool) -> str:
    if truncated:
        return "unclassified"
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "unclassified"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, str) and error in _TOKEN_ERROR_CATEGORIES:
        return error
    return "unclassified"


def _mcp_startup_method(body: bytes, *, truncated: bool) -> str | None:
    if truncated:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    method = payload.get("method") if isinstance(payload, dict) else None
    if isinstance(method, str) and method in _MCP_INITIALIZATION_METHODS:
        return method
    return None


def _mcp_http_failure_category(status: int) -> str:
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "origin_or_host_rejected"
    if status == 400:
        return "bad_request"
    if status == 404:
        return "not_found"
    if status >= 500:
        return "server_error"
    return "http_error"


def _mcp_startup_outcome(
    body: bytes,
    request_body: bytes,
    *,
    status: int,
    method: str,
    truncated: bool,
    request_truncated: bool,
) -> str:
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "origin_or_host_rejected"
    if status >= 500:
        return "server_error"
    if truncated:
        return "unclassified"
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "unclassified"
    if not isinstance(payload, dict):
        return "unclassified"
    try:
        request = json.loads(request_body) if not request_truncated else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        request = None
    params = request.get("params") if isinstance(request, dict) else None
    result = payload.get("result")
    if isinstance(result, dict):
        if method == "initialize" and isinstance(params, dict):
            requested_version = params.get("protocolVersion")
            if result.get("protocolVersion") == requested_version:
                return "success"
            if isinstance(result.get("protocolVersion"), str):
                return "protocol_version_counteroffer"
        if method == "server/discover" and isinstance(params, dict):
            metadata = params.get("_meta")
            requested_version = (
                metadata.get("io.modelcontextprotocol/protocolVersion")
                if isinstance(metadata, dict)
                else None
            )
            supported_versions = result.get("supportedVersions")
            if isinstance(supported_versions, list):
                return (
                    "success"
                    if requested_version in supported_versions
                    else "unsupported_protocol_version"
                )
    error = payload.get("error")
    if isinstance(error, dict):
        code_categories = {
            -32020: "routing_header_mismatch",
            -32022: "unsupported_protocol_version",
            -32600: "invalid_request",
            -32602: "invalid_params",
        }
        category = code_categories.get(error.get("code"))
        if category:
            return category
        return "jsonrpc_error"
    if status >= 400:
        return "http_error"
    return "unexpected_response"


class OAuthSecurityMiddleware:
    """Apply exact Origin policy and resource validation around SDK routes.

    MCP Streamable HTTP Host/Origin validation remains in the SDK transport.
    FastAPI's TrustedHostMiddleware checks Host for every route. The SDK 2.3
    OAuth route helper adds wildcard CORS, so this wrapper removes those headers;
    the outer FastAPI CORS middleware then adds only configured exact origins.
    """

    _OAUTH_ENDPOINTS = _OAUTH_ENDPOINTS

    def __init__(
        self,
        app,
        *,
        allowed_origins: list[str],
        issuer_url: str,
        resource_url: str,
    ) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)
        self.issuer_url = issuer_url.rstrip("/")
        self.resource_url = resource_url.rstrip("/")
        self.registration_limiter = _BoundedRateLimiter()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        origin_header = headers.get(b"origin")
        origin = origin_header.decode("latin-1") if origin_header else None
        is_oauth_endpoint = path in self._OAUTH_ENDPOINTS

        if is_oauth_endpoint and origin and origin not in self.allowed_origins:
            if path == "/token":
                logger.warning(
                    "oauth token exchange outcome=failed status=403 category=origin_rejected"
                )
            await self._json_error(
                send,
                status=403,
                error="invalid_request",
                description="Request origin is not allowed.",
            )
            return

        replay_receive = receive
        if path == "/register" and method == "POST":
            client = scope.get("client")
            client_key = str(client[0]) if client else "unknown"
            if not self.registration_limiter.allow(client_key):
                await self._json_error(
                    send,
                    status=429,
                    error="temporarily_unavailable",
                    description="Too many client registrations. Try again later.",
                    headers=[(b"retry-after", str(DCR_RATE_LIMIT_WINDOW_SECONDS).encode())],
                )
                return
            body, too_large = await self._read_limited_body(receive)
            if too_large:
                logger.warning(
                    "oauth token exchange outcome=failed status=413 category=request_too_large"
                )
                await self._json_error(
                    send,
                    status=413,
                    error="invalid_client_metadata",
                    description="Client registration metadata is too large.",
                )
                return
            try:
                registration = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                registration = None
            if isinstance(registration, dict) and "redirect_uris" in registration:
                redirect_uris = registration["redirect_uris"]
                if not isinstance(redirect_uris, list) or not redirect_uris or any(
                    not isinstance(uri, str) or not _is_safe_redirect_uri(uri)
                    for uri in redirect_uris
                ):
                    await self._json_error(
                        send,
                        status=400,
                        error="invalid_redirect_uri",
                        description=(
                            "Redirect URIs must use HTTPS or loopback HTTP and must not "
                            "contain user information or fragments."
                        ),
                    )
                    return

            sent = False

            async def replay_registration():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            replay_receive = replay_registration

        if path == "/token" and method == "POST":
            body, too_large = await self._read_limited_body(receive)
            if too_large:
                await self._json_error(
                    send,
                    status=413,
                    error="invalid_request",
                    description="Token request is too large.",
                )
                return
            content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            try:
                form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            except (UnicodeDecodeError, ValueError):
                form = {}
            resources = form.get("resource", [])
            if content_type != b"application/x-www-form-urlencoded":
                logger.warning(
                    "oauth token exchange outcome=failed status=400 category=invalid_request"
                )
                await self._json_error(
                    send,
                    status=400,
                    error="invalid_target",
                    description="The requested resource is not GrowthLoop MCP.",
                )
                return
            if resources != [self.resource_url]:
                logger.warning(
                    "oauth token exchange outcome=failed status=400 category=invalid_target"
                )
                await self._json_error(
                    send,
                    status=400,
                    error="invalid_target",
                    description="The requested resource is not GrowthLoop MCP.",
                )
                return

            sent = False

            async def replay_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            replay_receive = replay_receive

        mcp_request_body = bytearray()
        mcp_request_truncated = False
        mcp_response_body = bytearray()
        mcp_response_truncated = False
        token_error_body = bytearray()
        token_error_truncated = False
        response_status: int | None = None

        async def secure_send(message):
            nonlocal response_status
            nonlocal mcp_response_truncated, token_error_truncated

            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                if path == "/mcp" and method == "POST" and response_status >= 400:
                    mcp_method = _mcp_startup_method(
                        bytes(mcp_request_body), truncated=mcp_request_truncated
                    )
                    if mcp_method is None:
                        logger.warning(
                            "mcp request outcome=failed status=%d category=%s "
                            "bearer_present=%s origin_present=%s",
                            response_status,
                            _mcp_http_failure_category(response_status),
                            b"authorization" in headers,
                            origin_header is not None,
                        )

                message_headers = list(message.get("headers", []))
                if is_oauth_endpoint:
                    # SDK OAuth routes allow '*'. The outer FastAPI CORS middleware
                    # supplies ACAO only for its exact configured origin list.
                    message_headers = [
                        (key, value)
                        for key, value in message_headers
                        if key.lower() != b"access-control-allow-origin"
                    ]

                if path == "/authorize":
                    message_headers = self._add_issuer_to_redirect(message_headers)

                await send({**message, "headers": message_headers})
                return

            if message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if (
                    path == "/token"
                    and response_status is not None
                    and response_status >= 400
                    and len(token_error_body) + len(chunk) <= MAX_DIAGNOSTIC_RESPONSE_BYTES
                ):
                    token_error_body.extend(chunk)
                elif path == "/token" and response_status is not None and response_status >= 400:
                    token_error_truncated = True

                mcp_method = (
                    _mcp_startup_method(
                        bytes(mcp_request_body), truncated=mcp_request_truncated
                    )
                    if path == "/mcp" and method == "POST"
                    else None
                )
                if mcp_method is not None:
                    if len(mcp_response_body) + len(chunk) <= MAX_DIAGNOSTIC_RESPONSE_BYTES:
                        mcp_response_body.extend(chunk)
                    else:
                        mcp_response_truncated = True

                if not message.get("more_body", False):
                    if path == "/token" and response_status is not None:
                        if response_status < 400:
                            logger.info(
                                "oauth token exchange outcome=success status=%d",
                                response_status,
                            )
                        else:
                            logger.warning(
                                "oauth token exchange outcome=failed status=%d category=%s",
                                response_status,
                                _token_failure_category(
                                    bytes(token_error_body), truncated=token_error_truncated
                                ),
                            )
                    if mcp_method is not None and response_status is not None:
                        outcome = _mcp_startup_outcome(
                            bytes(mcp_response_body),
                            bytes(mcp_request_body),
                            status=response_status,
                            method=mcp_method,
                            truncated=mcp_response_truncated,
                            request_truncated=mcp_request_truncated,
                        )
                        log = logger.info if outcome == "success" else logger.warning
                        log(
                            "mcp initialization outcome=%s method=%s status=%d",
                            outcome,
                            mcp_method,
                            response_status,
                        )
                await send(message)
                return

            await send(message)

        if path == "/.well-known/oauth-authorization-server":
            await self._send_metadata_with_issuer_support(scope, replay_receive, secure_send)
            return

        application_receive = replay_receive
        if path == "/mcp" and method == "POST":
            async def capture_mcp_request_body():
                nonlocal mcp_request_truncated
                request_message = await replay_receive()
                if request_message["type"] == "http.request":
                    chunk = request_message.get("body", b"")
                    if len(mcp_request_body) + len(chunk) <= MAX_DIAGNOSTIC_BODY_BYTES:
                        mcp_request_body.extend(chunk)
                    else:
                        mcp_request_truncated = True
                return request_message

            application_receive = capture_mcp_request_body

        await self.app(scope, application_receive, secure_send)

    async def _send_metadata_with_issuer_support(self, scope, receive, send) -> None:
        start_message = None
        body_parts: list[bytes] = []

        async def buffer_send(message):
            nonlocal start_message
            if message["type"] == "http.response.start":
                start_message = message
                return
            if message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                body = b"".join(body_parts)
                try:
                    payload = json.loads(body)
                    payload["authorization_response_iss_parameter_supported"] = True
                    auth_methods = payload.get(
                        "token_endpoint_auth_methods_supported"
                    )
                    if not isinstance(auth_methods, list):
                        auth_methods = []
                    if "none" not in auth_methods:
                        auth_methods.append("none")
                    payload["token_endpoint_auth_methods_supported"] = auth_methods
                    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                    start = dict(start_message or {})
                    start_headers = [
                        (key, value)
                        for key, value in start.get("headers", [])
                        if key.lower() != b"content-length"
                    ]
                    start_headers.append((b"content-length", str(len(body)).encode()))
                    start["headers"] = start_headers
                    if start:
                        await send(start)
                    await send({"type": "http.response.body", "body": body, "more_body": False})
                    return
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
                if start_message:
                    await send(start_message)
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        await self.app(scope, receive, buffer_send)

    def _add_issuer_to_redirect(self, headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
        output: list[tuple[bytes, bytes]] = []
        for key, value in headers:
            if key.lower() != b"location":
                output.append((key, value))
                continue
            location = value.decode("latin-1")
            parsed = urlsplit(location)
            # The initial redirect leads to GrowthLoop's consent screen, not
            # back to the OAuth client. SDK-generated OAuth errors return to
            # the registered redirect URI and need the same issuer marker.
            issuer_origin = urlsplit(self.issuer_url)
            location_query = parse_qs(parsed.query, keep_blank_values=True)
            is_consent = (
                parsed.path == "/oauth/consent"
                and parsed.netloc.lower() == issuer_origin.netloc.lower()
                and set(location_query) == {"request_id"}
            )
            if not is_consent:
                query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key != "iss"]
                query.append(("iss", self.issuer_url))
                location = urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
                )
                value = location.encode("latin-1")
            output.append((key, value))
        return output

    @staticmethod
    async def _read_limited_body(receive) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_TOKEN_REQUEST_BODY_BYTES:
                return b"", True
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        return b"".join(chunks), False

    @staticmethod
    async def _json_error(
        send,
        *,
        status: int,
        error: str,
        description: str,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        body = json.dumps(
            {"error": error, "error_description": description}, separators=(",", ":")
        ).encode("utf-8")
        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
            (b"pragma", b"no-cache"),
        ]
        if headers:
            response_headers.extend(headers)
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})


def mcp_auth_settings(issuer_url: str, resource_url: str) -> AuthSettings:
    """Build SDK auth settings for the remote MCP resource server."""
    return AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=resource_url,
        validate_token_resource=True,
        required_scopes=[OAUTH_SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[OAUTH_SCOPE],
            default_scopes=[OAUTH_SCOPE],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )


@dataclass(frozen=True, slots=True)
class ConsentRequest:
    request_id: str
    client_name: str
    scopes: tuple[str, ...]
    approval_nonce: str


@dataclass(frozen=True, slots=True)
class _PendingAuthorization:
    client_id: str
    params: AuthorizationParams
    approval_nonce: str
    expires_at: float


class GrowthLoopOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Short-lived, revocable OAuth tokens backed by process memory."""

    def __init__(self, issuer_url: str, resource_url: str) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.resource_url = resource_url.rstrip("/")
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._client_last_seen: dict[str, float] = {}
        self._requests: dict[str, _PendingAuthorization] = {}
        self._codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._refresh_to_access: dict[str, str] = {}
        self._access_to_refresh: dict[str, str] = {}
        self._lock = threading.RLock()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._lock:
            now = time.time()
            self._purge_expired_locked(now)
            client = self._clients.get(client_id)
            if client is not None:
                self._client_last_seen[client_id] = now
            return client.model_copy(deep=True) if client else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.redirect_uris:
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description="At least one redirect URI is required",
            )
        if any(not _is_safe_redirect_uri(str(uri)) for uri in client_info.redirect_uris):
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description=(
                    "Redirect URIs must use HTTPS or loopback HTTP and must not "
                    "contain user information or fragments"
                ),
            )
        with self._lock:
            self._purge_expired_locked()
            if (
                client_info.client_id not in self._clients
                and len(self._clients) >= MAX_REGISTERED_CLIENTS
            ):
                raise RegistrationError(
                    error="invalid_client_metadata",
                    error_description="Client registration limit reached",
                )
            self._clients[client_info.client_id] = client_info.model_copy(deep=True)
            self._client_last_seen[client_info.client_id] = time.time()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        requested_scopes = params.scopes or [OAUTH_SCOPE]
        if OAUTH_SCOPE not in requested_scopes or any(
            scope != OAUTH_SCOPE for scope in requested_scopes
        ):
            raise AuthorizeError(
                error="invalid_scope",
                error_description="GrowthLoop supports only the experiments scope",
            )
        if params.resource != self.resource_url:
            raise AuthorizeError(
                error="invalid_target",
                error_description="The requested resource is not GrowthLoop MCP",
            )

        request_id = secrets.token_urlsafe(32)
        pending = _PendingAuthorization(
            client_id=client.client_id,
            params=params.model_copy(update={"scopes": requested_scopes}),
            approval_nonce=secrets.token_urlsafe(32),
            expires_at=time.time() + OAUTH_REQUEST_TTL_SECONDS,
        )
        with self._lock:
            self._purge_expired_locked()
            if len(self._requests) >= MAX_PENDING_AUTHORIZATIONS:
                raise AuthorizeError(
                    error="temporarily_unavailable",
                    error_description="Authorization is temporarily unavailable",
                )
            self._requests[request_id] = pending
        return f"{self.issuer_url}/oauth/consent?{urlencode({'request_id': request_id})}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self._lock:
            code = self._codes.get(authorization_code)
            if (
                code is None
                or code.client_id != client.client_id
                or code.expires_at <= time.time()
            ):
                self._codes.pop(authorization_code, None)
                return None
            return code.model_copy(deep=True)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with self._lock:
            code = self._codes.pop(authorization_code.code, None)
            if (
                code is None
                or code.client_id != client.client_id
                or code.expires_at <= time.time()
                or code.resource != self.resource_url
            ):
                raise TokenError(
                    error="invalid_grant",
                    error_description="The authorization code is invalid or expired",
                )
            self._client_last_seen[client.client_id] = time.time()
            return self._issue_tokens_locked(
                client_id=code.client_id,
                scopes=code.scopes,
                subject=code.subject or "owner",
            )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        key = self._token_key(refresh_token)
        with self._lock:
            stored = self._refresh_tokens.get(key)
            if (
                stored is None
                or stored.client_id != client.client_id
                or stored.resource != self.resource_url
                or (stored.expires_at is not None and stored.expires_at <= time.time())
            ):
                self._remove_refresh_locked(key)
                return None
            return stored.model_copy(deep=True)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        key = self._token_key(refresh_token.token)
        with self._lock:
            stored = self._refresh_tokens.get(key)
            if (
                stored is None
                or stored.client_id != client.client_id
                or stored.resource != self.resource_url
                or stored.expires_at is None
                or stored.expires_at <= time.time()
                or not set(scopes).issubset(stored.scopes)
            ):
                self._remove_refresh_locked(key)
                raise TokenError(
                    error="invalid_grant",
                    error_description="The refresh token is invalid or expired",
                )
            self._remove_refresh_locked(key)
            self._client_last_seen[client.client_id] = time.time()
            return self._issue_tokens_locked(
                client_id=stored.client_id,
                scopes=scopes,
                subject=stored.subject or "owner",
            )

    async def load_access_token(self, token: str) -> AccessToken | None:
        key = self._token_key(token)
        with self._lock:
            stored = self._access_tokens.get(key)
            if stored is None or (stored.expires_at and stored.expires_at <= time.time()):
                self._remove_access_locked(key, revoke_refresh=False)
                return None
            self._client_last_seen[stored.client_id] = time.time()
            return stored.model_copy(deep=True)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        key = self._token_key(token.token)
        with self._lock:
            if isinstance(token, AccessToken):
                refresh_key = self._access_to_refresh.get(key)
                self._remove_access_locked(key)
                if refresh_key:
                    self._remove_refresh_locked(refresh_key)
            else:
                self._remove_refresh_locked(key)

    def get_consent_request(self, request_id: str) -> ConsentRequest | None:
        with self._lock:
            pending = self._requests.get(request_id)
            if pending is None or pending.expires_at <= time.time():
                self._requests.pop(request_id, None)
                return None
            client = self._clients.get(pending.client_id)
            if client is None:
                self._requests.pop(request_id, None)
                return None
            return ConsentRequest(
                request_id=request_id,
                client_name=client.client_name or "Remote MCP client",
                scopes=tuple(pending.params.scopes or [OAUTH_SCOPE]),
                approval_nonce=pending.approval_nonce,
            )

    def verify_consent_nonce(self, request_id: str, nonce: str) -> bool:
        consent = self.get_consent_request(request_id)
        return bool(
            consent
            and nonce.isascii()
            and hmac.compare_digest(consent.approval_nonce, nonce)
        )

    def complete_consent(
        self, request_id: str, nonce: str, *, approved: bool
    ) -> str | None:
        with self._lock:
            pending = self._requests.get(request_id)
            if pending is None:
                return None
            if pending.expires_at <= time.time():
                self._requests.pop(request_id, None)
                return None
            if not nonce.isascii() or not hmac.compare_digest(
                pending.approval_nonce, nonce
            ):
                return None
            self._requests.pop(request_id, None)
            params = pending.params
            if approved:
                self._purge_expired_locked()
                if len(self._codes) >= MAX_AUTHORIZATION_CODES:
                    return None
                code_value = secrets.token_urlsafe(32)
                self._codes[code_value] = AuthorizationCode(
                    code=code_value,
                    scopes=params.scopes or [OAUTH_SCOPE],
                    expires_at=time.time() + AUTHORIZATION_CODE_TTL_SECONDS,
                    client_id=pending.client_id,
                    code_challenge=params.code_challenge,
                    redirect_uri=params.redirect_uri,
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    resource=params.resource,
                    subject="owner",
                )
                return construct_redirect_uri(
                    str(params.redirect_uri),
                    code=code_value,
                    state=params.state,
                    iss=self.issuer_url,
                )
            return construct_redirect_uri(
                str(params.redirect_uri),
                error="access_denied",
                state=params.state,
                iss=self.issuer_url,
            )

    def _issue_tokens_locked(
        self, *, client_id: str, scopes: list[str], subject: str
    ) -> OAuthToken:
        self._purge_expired_locked()
        if len(self._refresh_tokens) >= MAX_ACTIVE_TOKEN_PAIRS:
            raise TokenError(
                error="invalid_request",
                error_description="Token service is temporarily unavailable",
            )
        now = int(time.time())
        access_value = secrets.token_urlsafe(32)
        refresh_value = secrets.token_urlsafe(48)
        access_key = self._token_key(access_value)
        refresh_key = self._token_key(refresh_value)
        self._access_tokens[access_key] = AccessToken(
            token=access_value,
            client_id=client_id,
            scopes=list(scopes),
            expires_at=now + ACCESS_TOKEN_TTL_SECONDS,
            resource=self.resource_url,
            subject=subject,
        )
        self._refresh_tokens[refresh_key] = RefreshToken(
            token=refresh_value,
            client_id=client_id,
            scopes=list(scopes),
            expires_at=now + REFRESH_TOKEN_TTL_SECONDS,
            resource=self.resource_url,
            subject=subject,
        )
        self._refresh_to_access[refresh_key] = access_key
        self._access_to_refresh[access_key] = refresh_key
        return OAuthToken(
            access_token=access_value,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh_value,
        )

    def _remove_refresh_locked(self, key: str) -> None:
        self._refresh_tokens.pop(key, None)
        access_key = self._refresh_to_access.pop(key, None)
        if access_key:
            self._access_tokens.pop(access_key, None)
            self._access_to_refresh.pop(access_key, None)

    def _remove_access_locked(self, key: str, *, revoke_refresh: bool = True) -> None:
        self._access_tokens.pop(key, None)
        refresh_key = self._access_to_refresh.pop(key, None)
        if refresh_key and revoke_refresh:
            self._refresh_tokens.pop(refresh_key, None)
            self._refresh_to_access.pop(refresh_key, None)

    def _purge_expired_locked(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for client_id, last_seen in list(self._client_last_seen.items()):
            if last_seen <= now - CLIENT_INACTIVITY_TTL_SECONDS:
                self._remove_client_locked(client_id)
        for key, request in list(self._requests.items()):
            if request.expires_at <= now:
                self._requests.pop(key, None)
        for key, code in list(self._codes.items()):
            if code.expires_at <= now:
                self._codes.pop(key, None)
        for key, token in list(self._refresh_tokens.items()):
            if token.expires_at and token.expires_at <= now:
                self._remove_refresh_locked(key)
        for key, token in list(self._access_tokens.items()):
            if token.expires_at and token.expires_at <= now:
                self._remove_access_locked(key, revoke_refresh=False)

    def _remove_client_locked(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        self._client_last_seen.pop(client_id, None)
        for key, request in list(self._requests.items()):
            if request.client_id == client_id:
                self._requests.pop(key, None)
        for key, code in list(self._codes.items()):
            if code.client_id == client_id:
                self._codes.pop(key, None)
        for key, token in list(self._refresh_tokens.items()):
            if token.client_id == client_id:
                self._remove_refresh_locked(key)
        for key, token in list(self._access_tokens.items()):
            if token.client_id == client_id:
                self._remove_access_locked(key, revoke_refresh=False)

    @staticmethod
    def _token_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_consent_route(
    server,
    provider: GrowthLoopOAuthProvider,
    owner_auth: OwnerAuthService,
    *,
    production: bool,
    issuer_origin: str,
):
    """Add the first-party owner login and approval page to the SDK app."""

    @server.custom_route("/oauth/consent", methods=["GET", "POST"], include_in_schema=False)
    async def consent_route(request: Request) -> Response:
        request_id = request.query_params.get("request_id", "")
        consent = provider.get_consent_request(request_id)
        if consent is None:
            return _consent_response(
                "This authorization request has expired. Return to Claude and try again.",
                status_code=400,
            )

        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session = owner_auth.get_session(session_id)
        if request.method == "GET":
            return _consent_response(
                _consent_html(
                    consent,
                    authenticated=session is not None,
                    message=None,
                    csrf_token=session.csrf_token if session else None,
                )
            )

        origin = request.headers.get("origin")
        # Browser forms submitted from an opaque-origin context serialize
        # Origin as "null". Some clients may omit it entirely. Keep exact
        # origin checks whenever a usable origin is present; for absent or
        # opaque origins, the request-bound approval nonce below is required,
        # and an authenticated approval also requires the session CSRF token.
        origin_unavailable = origin is None or origin == "null"
        if not origin_unavailable and (
            origin not in owner_auth.allowed_origins
            or (production and origin != issuer_origin)
        ):
            return _consent_response("The request origin is not allowed.", status_code=403)

        try:
            form = await request.form()
        except Exception:
            return _consent_response("Invalid authorization request.", status_code=400)
        nonce = str(form.get("approval_nonce", ""))
        if not provider.verify_consent_nonce(request_id, nonce):
            return _consent_response(
                "This authorization request has expired or is invalid.",
                status_code=400,
            )

        if form.get("action") == "login":
            password = str(form.get("password", ""))
            if not 1 <= len(password) <= 1024:
                return _consent_response(
                    _consent_html(
                        consent,
                        authenticated=False,
                        message="The password is incorrect.",
                    ),
                    status_code=401,
                )
            try:
                new_session_id, _ = owner_auth.login(
                    password,
                    _client_key(request),
                )
            except LoginRateLimited:
                return _consent_response(
                    _consent_html(
                        consent,
                        authenticated=False,
                        message="Too many attempts. Try again later.",
                    ),
                    status_code=429,
                )
            except InvalidOwnerPassword:
                return _consent_response(
                    _consent_html(
                        consent,
                        authenticated=False,
                        message="The password is incorrect.",
                    ),
                    status_code=401,
                )
            response = RedirectResponse(
                url=f"/oauth/consent?{urlencode({'request_id': request_id})}",
                status_code=303,
                headers={"Cache-Control": "no-store"},
            )
            owner_auth.set_session_cookie(response, new_session_id)
            return response

        session = owner_auth.get_session(session_id)
        if session is None or not owner_auth.verify_csrf(
            session, str(form.get("csrf_token", ""))
        ):
            return _consent_response(
                _consent_html(
                    consent,
                    authenticated=session is not None,
                    message="Your session expired. Sign in and try again.",
                    csrf_token=session.csrf_token if session else None,
                ),
                status_code=403,
            )

        approved = form.get("action") == "approve"
        redirect_url = provider.complete_consent(
            request_id, nonce, approved=approved
        )
        if redirect_url is None:
            return _consent_response("This authorization request has expired.", status_code=400)
        return RedirectResponse(
            url=redirect_url,
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )

    return consent_route


def _consent_html(
    consent: ConsentRequest,
    *,
    authenticated: bool,
    message: str | None,
    csrf_token: str | None = None,
) -> str:
    client_name = html.escape(consent.client_name)
    form_action = html.escape(
        f"?{urlencode({'request_id': consent.request_id})}", quote=True
    )
    nonce = html.escape(consent.approval_nonce, quote=True)
    message_html = f'<p role="alert">{html.escape(message)}</p>' if message else ""
    if authenticated:
        csrf = html.escape(csrf_token or "", quote=True)
        actions = (
            f'<input type="hidden" name="csrf_token" value="{csrf}">'
            '<button type="submit" name="action" value="approve">Allow access</button>'
            '<button type="submit" name="action" value="deny">Deny</button>'
        )
        intro = f"Allow {client_name} to access and manage your GrowthLoop experiments?"
    else:
        actions = (
            '<label for="owner-password">Owner password</label>'
            '<input id="owner-password" name="password" type="password" '
            'autocomplete="current-password" required maxlength="1024">'
            '<button type="submit" name="action" value="login">Sign in and review</button>'
        )
        intro = "Sign in with the GrowthLoop owner password to review this connection."
    return (
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>GrowthLoop authorization</title><body>"
        "<main><h1>GrowthLoop</h1>"
        f"{message_html}<p>{html.escape(intro)}</p>"
        f'<form method="post" action="{form_action}" data-consent-form>'
        f'<input type="hidden" name="approval_nonce" value="{nonce}">'
        f"{actions}</form>"
        f"<script>{_CONSENT_SUBMIT_SCRIPT}</script></main></body></html>"
    )


def _consent_response(body: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        body,
        status_code=status_code,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'sha256-{_CONSENT_SUBMIT_SCRIPT_HASH}'; "
                "form-action 'self'; base-uri 'none'; "
                "frame-ancestors 'none'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"
