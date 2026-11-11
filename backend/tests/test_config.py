"""Tests for development and production application configuration."""

import secrets

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.url import normalize_database_url


HOSTED_DATABASE_URL = (
    "postgresql://growthloop:secret-value@ep-example.neon.tech/growthloop"
    "?sslmode=require"
)
PRODUCTION_ORIGINS = "https://growthloop.example.com"
PRODUCTION_MCP_HOSTS = "growthloop.example.com"
PRODUCTION_MCP_ORIGINS = ""
PRODUCTION_MCP_ISSUER = "https://growthloop.example.com"
TEST_OWNER_PASSWORD = secrets.token_urlsafe(24)


def _production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "database_url": HOSTED_DATABASE_URL,
        "cors_origins": PRODUCTION_ORIGINS,
        "mcp_allowed_hosts": PRODUCTION_MCP_HOSTS,
        "mcp_allowed_origins": PRODUCTION_MCP_ORIGINS,
        "mcp_issuer_url": PRODUCTION_MCP_ISSUER,
        "owner_password": TEST_OWNER_PASSWORD,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _clear_settings_environment(monkeypatch) -> None:
    for name in (
        "APP_ENV",
        "DEBUG",
        "DATABASE_URL",
        "CORS_ORIGINS",
        "MCP_ALLOWED_HOSTS",
        "MCP_ALLOWED_ORIGINS",
        "MCP_ISSUER_URL",
        "OWNER_PASSWORD",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT_SECONDS",
        "DB_POOL_RECYCLE_SECONDS",
        "DB_CONNECT_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_development_defaults_remain_compatible(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.debug is False
    assert settings.database_url == (
        "postgresql+psycopg://postgres:postgres@localhost:5432/growthloop"
    )
    assert settings.cors_origins == (
        "http://localhost:5173,http://127.0.0.1:5173"
    )
    assert settings.mcp_allowed_host_list == [
        "localhost",
        "localhost:8000",
        "127.0.0.1",
        "127.0.0.1:8000",
        "[::1]",
        "[::1]:8000",
        "testserver",
    ]
    assert settings.db_pool_size == 2
    assert settings.db_max_overflow == 0


def test_development_debug_can_be_enabled_explicitly(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    settings = Settings(_env_file=None, debug=True)

    assert settings.debug is True


def test_production_requires_explicit_database_and_cors(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, app_env="production")

    message = str(error.value)
    assert "DATABASE_URL" in message
    assert "CORS_ORIGINS" in message
    assert "MCP_ALLOWED_HOSTS" in message
    assert "MCP_ALLOWED_ORIGINS" in message
    assert "MCP_ISSUER_URL" in message
    assert "OWNER_PASSWORD" in message
    assert "postgres:postgres" not in message


def test_production_defaults_debug_off(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    settings = _production_settings()

    assert settings.debug is False


def test_production_environment_variables_are_loaded(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", HOSTED_DATABASE_URL)
    monkeypatch.setenv("CORS_ORIGINS", PRODUCTION_ORIGINS)
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", PRODUCTION_MCP_HOSTS)
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", PRODUCTION_MCP_ORIGINS)
    monkeypatch.setenv("MCP_ISSUER_URL", PRODUCTION_MCP_ISSUER)
    monkeypatch.setenv("OWNER_PASSWORD", TEST_OWNER_PASSWORD)

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.database_url == HOSTED_DATABASE_URL
    assert settings.cors_origins == PRODUCTION_ORIGINS
    assert settings.mcp_allowed_host_list == [PRODUCTION_MCP_HOSTS]
    assert settings.mcp_allowed_origin_list == []
    assert settings.mcp_resource_url == f"{PRODUCTION_MCP_ISSUER}/mcp"
    assert settings.debug is False


def test_production_rejects_explicit_debug_true(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    with pytest.raises(ValidationError, match="DEBUG must be false"):
        _production_settings(debug=True)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://postgres:postgres@localhost:5432/growthloop",
        "postgresql://postgres:postgres@127.0.0.1:5432/growthloop",
    ],
)
def test_production_rejects_local_database_urls(monkeypatch, database_url) -> None:
    _clear_settings_environment(monkeypatch)

    with pytest.raises(ValidationError, match="hosted PostgreSQL"):
        _production_settings(database_url=database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://growthloop:secret@ep-example.neon.tech/growthloop",
        "postgresql://growthloop:secret@ep-example.neon.tech/growthloop?sslmode=disable",
        "postgresql://growthloop:secret@ep-example.neon.tech/growthloop?sslmode=allow",
        "postgresql://growthloop:secret@ep-example.neon.tech/growthloop?sslmode=require&sslmode=disable",
        "postgresql://growthloop:secret@ep-example.neon.tech/growthloop?SSLMODE=require",
        "postgresql://growthloop:secret@ep-example.neon.tech/growthloop?sslmode=REQUIRE",
    ],
)
def test_production_rejects_database_urls_without_secure_tls(
    monkeypatch, database_url
) -> None:
    _clear_settings_environment(monkeypatch)

    with pytest.raises(ValidationError, match="explicitly require PostgreSQL TLS"):
        _production_settings(database_url=database_url)


def test_production_rejects_local_cors_origins(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    with pytest.raises(ValidationError, match="exact HTTPS origins"):
        _production_settings(cors_origins="http://localhost:5173")


def test_production_rejects_wildcard_mcp_hosts(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    with pytest.raises(ValidationError, match="MCP_ALLOWED_HOSTS"):
        _production_settings(mcp_allowed_hosts="*.example.com")


def test_production_rejects_http_mcp_origins(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    with pytest.raises(ValidationError, match="MCP_ALLOWED_ORIGINS"):
        _production_settings(mcp_allowed_origins="http://client.example.com")


def test_database_url_is_not_in_settings_repr(monkeypatch) -> None:
    _clear_settings_environment(monkeypatch)

    settings = _production_settings()

    assert "secret-value" not in repr(settings)


def test_neon_url_uses_psycopg_and_preserves_encoded_credentials_and_ssl() -> None:
    url = normalize_database_url(
        "postgresql://growthloop:p%40ss%3Aword@ep-example.neon.tech/growthloop"
        "?sslmode=require&channel_binding=require"
    )

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "growthloop"
    assert url.password == "p@ss:word"
    assert url.host == "ep-example.neon.tech"
    assert url.database == "growthloop"
    assert url.query["sslmode"] == "require"
    assert url.query["channel_binding"] == "require"
    assert "p%40ss%3Aword" in url.render_as_string(hide_password=False)


def test_psycopg_url_is_preserved() -> None:
    url = normalize_database_url(
        "postgresql+psycopg://user:pass@db.example.com/growthloop?sslmode=require"
    )

    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "require"


def test_non_postgresql_database_url_is_rejected_without_echoing_value() -> None:
    with pytest.raises(ValueError, match="PostgreSQL with psycopg 3") as error:
        normalize_database_url("sqlite:///private-secret.db")

    assert "private-secret" not in str(error.value)
