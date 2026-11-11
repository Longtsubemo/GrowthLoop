"""Application settings loaded from environment variables.

Values are read from the process environment and, if present, a ``.env``
file in the working directory or the repository root (so a single root
``.env`` works when the server is started from ``backend/``). See
``.env.example`` at the repository root for the available variables.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """GrowthLoop backend configuration."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "GrowthLoop"
    app_env: Literal["development", "production"] = "development"
    # The app previously used FastAPI's secure debug=False default. Keep that
    # behavior unless local development explicitly opts in with DEBUG=true.
    debug: bool = False
    # Defaults match the local docker-compose PostgreSQL service.
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/growthloop",
        repr=False,
    )
    # Owner credentials are accepted only by the backend; never serialize them.
    owner_password: str | None = Field(default=None, repr=False)
    owner_session_ttl_seconds: int = Field(default=28_800, ge=300, le=86_400)
    # OAuth issuer for remote MCP authorization. This is the API's public base URL.
    mcp_issuer_url: str = "http://localhost:8000"
    # Comma-separated CORS origins allowed to call the API from a browser
    # (the React dev server runs on its own origin). The defaults match
    # `npm run dev`; the Playwright suite overrides this via the env var.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # MCP transport checks are separate from API CORS. Hosts are exact
    # Host-header values; origins are exact browser origins.
    mcp_allowed_hosts: str = (
        "localhost,localhost:8000,127.0.0.1,127.0.0.1:8000,"
        "[::1],[::1]:8000,testserver"
    )
    mcp_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    db_pool_size: int = Field(default=2, ge=1, le=10)
    db_max_overflow: int = Field(default=0, ge=0, le=5)
    db_pool_timeout_seconds: float = Field(default=5, ge=1, le=60)
    db_pool_recycle_seconds: int = Field(default=300, ge=0, le=3600)
    db_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        """Apply environment-specific defaults and reject unsafe production setup."""
        explicitly_set = self.model_fields_set.copy()

        # Debug remains opt-in in development and is forbidden in production.
        if self.app_env == "production" and self.debug:
            raise ValueError("DEBUG must be false in production")

        if self.app_env == "production":
            missing = [
                env_name
                for field_name, env_name in (
                    ("database_url", "DATABASE_URL"),
                    ("cors_origins", "CORS_ORIGINS"),
                    ("mcp_allowed_hosts", "MCP_ALLOWED_HOSTS"),
                    ("mcp_allowed_origins", "MCP_ALLOWED_ORIGINS"),
                    ("owner_password", "OWNER_PASSWORD"),
                    ("mcp_issuer_url", "MCP_ISSUER_URL"),
                )
                if field_name not in explicitly_set
            ]
            if missing:
                raise ValueError(
                    "Production requires explicitly configured "
                    + " and ".join(missing)
                )

            self._validate_production_database_url()
            self._validate_production_cors_origins()
            self._validate_mcp_hosts(production=True)
            self._validate_mcp_origins(production=True)
            self._validate_mcp_issuer(production=True)
        else:
            self._validate_mcp_hosts(production=False)
            self._validate_mcp_origins(production=False)
            self._validate_mcp_issuer(production=False)

        if self.owner_password is not None and not 16 <= len(self.owner_password) <= 1024:
            raise ValueError("OWNER_PASSWORD must be between 16 and 1024 characters")

        return self

    def _validate_production_database_url(self) -> None:
        """Require hosted PostgreSQL over explicitly enabled TLS."""
        try:
            parsed = urlsplit(self.database_url)
            hostname = parsed.hostname
        except ValueError:
            raise ValueError(
                "DATABASE_URL must be a valid hosted PostgreSQL URL"
            ) from None

        if (
            parsed.scheme.lower()
            not in {"postgres", "postgresql", "postgresql+psycopg"}
            or not hostname
            or hostname.lower() in {"localhost", "::1"}
            or hostname.startswith("127.")
            or hostname == "0.0.0.0"
        ):
            raise ValueError("DATABASE_URL must point to hosted PostgreSQL")

        ssl_modes = [
            value
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key == "sslmode"
        ]
        if len(ssl_modes) != 1 or ssl_modes[0] not in {
            "require",
            "verify-ca",
            "verify-full",
        }:
            raise ValueError("DATABASE_URL must explicitly require PostgreSQL TLS")

    def _validate_production_cors_origins(self) -> None:
        """Require exact HTTPS origins for the production dashboard."""
        origins = [origin.strip() for origin in self.cors_origins.split(",")]
        if not origins or any(not origin for origin in origins):
            raise ValueError("CORS_ORIGINS must contain HTTPS dashboard origins")

        for origin in origins:
            try:
                parsed = urlsplit(origin)
                hostname = parsed.hostname
                _ = parsed.port
            except ValueError:
                raise ValueError(
                    "CORS_ORIGINS must contain exact HTTPS origins"
                ) from None
            if (
                parsed.scheme != "https"
                or not hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or "*" in origin
                or hostname.lower() in {"localhost", "::1"}
                or hostname.startswith("127.")
            ):
                raise ValueError("CORS_ORIGINS must contain exact HTTPS origins")

    def _validate_mcp_hosts(self, *, production: bool) -> None:
        """Reject empty or broad Host allowlists for the MCP transport."""
        hosts = [host.strip() for host in self.mcp_allowed_hosts.split(",")]
        if not hosts or any(not host for host in hosts):
            raise ValueError("MCP_ALLOWED_HOSTS must contain exact hostnames")

        for host in hosts:
            if (
                host == "*"
                or any(char in host for char in "/@?#\\")
                or any(char.isspace() for char in host)
                or (
                    "*" in host
                    and (
                        not host.endswith(":*")
                        or "*" in host[:-2]
                    )
                )
                or (production and host.endswith(":*"))
            ):
                raise ValueError("MCP_ALLOWED_HOSTS must contain exact hostnames")
            authority = host[:-2] if host.endswith(":*") else host
            try:
                parsed = urlsplit(f"//{authority}")
                _ = parsed.port
            except ValueError:
                raise ValueError(
                    "MCP_ALLOWED_HOSTS must contain valid hostnames"
                ) from None
            if (
                not parsed.hostname
                or "*" in parsed.hostname
                or parsed.path
                or parsed.username
                or parsed.password
            ):
                raise ValueError("MCP_ALLOWED_HOSTS must contain valid hostnames")
            hostname = parsed.hostname.lower()
            if production and (
                hostname in {"localhost", "::1", "testserver"}
                or hostname.startswith("127.")
                or hostname == "0.0.0.0"
            ):
                raise ValueError("MCP_ALLOWED_HOSTS must contain hosted hostnames")

    def _validate_mcp_origins(self, *, production: bool) -> None:
        """Require exact origins and HTTPS origins in production."""
        origins = [
            origin.strip()
            for origin in self.mcp_allowed_origins.split(",")
            if origin.strip()
        ]
        for origin in origins:
            try:
                parsed = urlsplit(origin)
                hostname = parsed.hostname
                _ = parsed.port
            except ValueError:
                raise ValueError(
                    "MCP_ALLOWED_ORIGINS must contain exact origins"
                ) from None
            if (
                parsed.scheme not in ({"https"} if production else {"http", "https"})
                or not hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or "*" in origin
            ):
                raise ValueError(
                    "MCP_ALLOWED_ORIGINS must contain exact HTTPS origins"
                    if production
                    else "MCP_ALLOWED_ORIGINS must contain exact origins"
                )
            if production and (
                hostname.lower() in {"localhost", "::1"}
                or hostname.startswith("127.")
                or hostname == "0.0.0.0"
            ):
                raise ValueError(
                    "MCP_ALLOWED_ORIGINS must contain exact HTTPS origins"
                )

    def _validate_mcp_issuer(self, *, production: bool) -> None:
        """Require an exact issuer URL hosted at an allowed MCP hostname."""
        try:
            parsed = urlsplit(self.mcp_issuer_url)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError:
            raise ValueError("MCP_ISSUER_URL must be an exact API base URL") from None

        if (
            parsed.scheme not in ({"https"} if production else {"http", "https"})
            or not hostname
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "MCP_ISSUER_URL must be an exact HTTPS API base URL"
                if production
                else "MCP_ISSUER_URL must be an exact API base URL"
            )

        self.mcp_issuer_url = self.mcp_issuer_url.rstrip("/")

        authority = parsed.netloc.lower()
        allowed_authorities = {
            host.strip().lower()
            for host in self.mcp_allowed_hosts.split(",")
            if host.strip() and not host.strip().endswith(":*")
        }
        if production and authority not in allowed_authorities:
            raise ValueError("MCP_ISSUER_URL host must appear in MCP_ALLOWED_HOSTS")
        if production and (
            hostname.lower() in {"localhost", "::1", "testserver"}
            or hostname.startswith("127.")
            or hostname == "0.0.0.0"
        ):
            raise ValueError("MCP_ISSUER_URL must use a hosted HTTPS hostname")

    @property
    def mcp_allowed_host_list(self) -> list[str]:
        """Return the configured MCP Host-header allowlist."""
        return [host.strip() for host in self.mcp_allowed_hosts.split(",")]

    @property
    def mcp_allowed_origin_list(self) -> list[str]:
        """Return the configured MCP Origin-header allowlist."""
        return [
            origin.strip()
            for origin in self.mcp_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def mcp_resource_url(self) -> str:
        """Return the remote MCP resource identifier used by OAuth."""
        return f"{self.mcp_issuer_url.rstrip('/')}/mcp"

    @property
    def mcp_issuer_origin(self) -> str:
        """Return the exact origin of the configured OAuth issuer."""
        issuer = urlsplit(self.mcp_issuer_url)
        return f"{issuer.scheme}://{issuer.netloc}"

    @property
    def allowed_origin_list(self) -> list[str]:
        """Return exact browser origins accepted for auth flows and CORS."""
        origins = [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]
        for origin in self.mcp_allowed_origin_list:
            if origin not in origins:
                origins.append(origin)
        issuer = urlsplit(self.mcp_issuer_url)
        issuer_origin = f"{issuer.scheme}://{issuer.netloc}"
        if issuer_origin not in origins:
            origins.append(issuer_origin)
        return origins

    @property
    def trusted_host_list(self) -> list[str]:
        """Return hostnames for app-wide Host-header validation."""
        values: list[str] = []
        for entry in self.mcp_allowed_hosts.split(","):
            host = entry.strip()
            if host.endswith(":*"):
                host = host[:-2]
            try:
                hostname = urlsplit(f"//{host}").hostname
            except ValueError:
                hostname = None
            if hostname and hostname not in values:
                values.append(hostname)
        return values


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
