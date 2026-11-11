"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.auth import auth_router
from app.api.experiments import experiments_router
from app.api.health import health_router
from app.core.auth import OwnerAuthService
from app.core.config import get_settings
from app.db.session import engine
from app.services.exceptions import ExperimentNotFoundError
from mcp_server.oauth import (
    GrowthLoopOAuthProvider,
    OAuthCorsPreflightGuardMiddleware,
    OAuthSecurityMiddleware,
    mcp_auth_settings,
)
from mcp_server.server import create_mcp_server


async def experiment_not_found_handler(
    request: Request, exc: ExperimentNotFoundError
) -> JSONResponse:
    """Translate the domain-level error into an HTTP 404 response."""
    return JSONResponse(
        status_code=404,
        content={"detail": f"Experiment {exc.experiment_id} not found"},
    )


class _MCPApplicationMount:
    """Forward mounted ASGI requests to the lifespan-owned MCP app."""

    def __init__(self) -> None:
        self._application: ASGIApp | None = None

    def set_application(self, application: ASGIApp | None) -> None:
        self._application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        application = self._application
        if application is None:
            await Response(
                "MCP service is unavailable", status_code=503
            )(scope, receive, send)
            return
        await application(scope, receive, send)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    mcp_mount = _MCPApplicationMount()
    owner_auth = OwnerAuthService(
        settings.owner_password,
        session_ttl_seconds=settings.owner_session_ttl_seconds,
        secure_cookie=settings.app_env == "production",
        allowed_origins=settings.allowed_origin_list,
    )
    oauth_provider = GrowthLoopOAuthProvider(
        settings.mcp_issuer_url,
        settings.mcp_resource_url,
    )
    issuer_origin = settings.mcp_issuer_origin

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Own the HTTP MCP manager and shared database pool lifecycle."""
        http_mcp_server = create_mcp_server(
            oauth_provider=oauth_provider,
            auth_settings=mcp_auth_settings(
                settings.mcp_issuer_url,
                settings.mcp_resource_url,
            ),
            owner_auth=owner_auth,
            production=settings.app_env == "production",
            issuer_origin=issuer_origin,
        )
        http_mcp_app = http_mcp_server.streamable_http_app(
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=settings.mcp_allowed_host_list,
                allowed_origins=settings.mcp_allowed_origin_list,
            ),
        )
        secured_http_mcp_app = OAuthSecurityMiddleware(
            http_mcp_app,
            allowed_origins=settings.mcp_allowed_origin_list,
            issuer_url=settings.mcp_issuer_url,
            resource_url=settings.mcp_resource_url,
        )
        manager = http_mcp_server.session_manager
        application.state.mcp_session_manager = manager
        try:
            # A mounted ASGI app does not run its own lifespan under FastAPI.
            # The host application must enter the manager context itself.
            async with manager.run():
                mcp_mount.set_application(secured_http_mcp_app)
                try:
                    yield
                finally:
                    mcp_mount.set_application(None)
        finally:
            engine.dispose()

    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.state.owner_auth = owner_auth
    app.state.oauth_provider = oauth_provider
    app.state.production = settings.app_env == "production"
    app.state.allowed_origins = settings.allowed_origin_list
    # The dashboard runs in the browser on a different origin than the API,
    # so cross-origin requests need CORS. Exact MCP origins are included too.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "X-CSRF-Token",
            "MCP-Protocol-Version",
            "MCP-Session-Id",
            "Last-Event-ID",
        ],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_host_list,
        www_redirect=False,
    )
    # Added last so this exact MCP-origin guard runs before FastAPI CORS handles
    # OAuth preflights using the broader dashboard + MCP origin set.
    app.add_middleware(
        OAuthCorsPreflightGuardMiddleware,
        allowed_origins=settings.mcp_allowed_origin_list,
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(experiments_router)
    # This final root mount carries both /mcp and the SDK OAuth endpoints.
    app.mount("/", mcp_mount, name="mcp-and-oauth")
    app.add_exception_handler(ExperimentNotFoundError, experiment_not_found_handler)
    return app


app = create_app()
