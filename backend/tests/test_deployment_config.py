"""Render Blueprint assertions for the free-tier deployment preparation."""

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _blueprint() -> dict:
    with (REPOSITORY_ROOT / "render.yaml").open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def _service(blueprint: dict, name: str) -> dict:
    return next(
        service for service in blueprint["services"] if service["name"] == name
    )


def _environment(service: dict) -> dict[str, dict]:
    return {item["key"]: item for item in service.get("envVars", [])}


def test_render_backend_uses_one_free_worker_and_database_readiness() -> None:
    blueprint = _blueprint()
    api = _service(blueprint, "growthloop-api")
    env = _environment(api)

    assert api["type"] == "web"
    assert api["runtime"] == "python"
    assert api["plan"] == "free"
    assert api["branch"] == "dev"
    assert api["rootDir"] == "backend"
    assert api["healthCheckPath"] == "/health/ready"
    assert "--host 0.0.0.0" in api["startCommand"]
    assert "--port $PORT" in api["startCommand"]
    assert "--workers 1" in api["startCommand"]
    assert "alembic" not in api["startCommand"].lower()
    assert "preDeployCommand" not in api
    assert api["autoDeployTrigger"] == "off"
    assert api["buildCommand"] == "pip install ."
    assert env["APP_ENV"]["value"] == "production"
    assert env["DEBUG"]["value"] == "false"
    assert env["PYTHON_VERSION"]["value"] == "3.12.12"
    assert env["DATABASE_URL"]["sync"] is False
    assert env["OWNER_PASSWORD"]["sync"] is False
    assert env["DB_POOL_SIZE"]["value"] == "1"
    assert env["DB_MAX_OVERFLOW"]["value"] == "0"
    assert env["MCP_ISSUER_URL"]["fromService"]["envVarKey"] == "RENDER_EXTERNAL_URL"
    assert env["MCP_ISSUER_URL"]["fromService"]["name"] == "growthloop-api"
    assert (
        env["MCP_ALLOWED_HOSTS"]["fromService"]["envVarKey"]
        == "RENDER_EXTERNAL_HOSTNAME"
    )
    assert env["MCP_ALLOWED_HOSTS"]["fromService"]["name"] == "growthloop-api"
    assert env["MCP_ALLOWED_ORIGINS"]["value"] == ""
    assert env["CORS_ORIGINS"]["sync"] is False
    assert "*" not in str(env["MCP_ALLOWED_HOSTS"])
    assert "*" not in str(env["CORS_ORIGINS"])


def test_render_static_site_builds_frontend_with_backend_url() -> None:
    blueprint = _blueprint()
    dashboard = _service(blueprint, "growthloop-dashboard")
    env = _environment(dashboard)

    assert dashboard["type"] == "web"
    assert dashboard["runtime"] == "static"
    assert dashboard["branch"] == "dev"
    assert dashboard["rootDir"] == "frontend"
    assert dashboard["buildCommand"] == "npm ci && npm run build"
    assert dashboard["staticPublishPath"] == "dist"
    assert dashboard["autoDeployTrigger"] == "off"
    assert set(env) == {"NODE_VERSION", "VITE_API_BASE_URL"}
    assert env["NODE_VERSION"]["value"] == "24.22.2"
    assert env["VITE_API_BASE_URL"]["fromService"]["name"] == "growthloop-api"
    assert (
        env["VITE_API_BASE_URL"]["fromService"]["envVarKey"]
        == "RENDER_EXTERNAL_URL"
    )
    assert (REPOSITORY_ROOT / "frontend" / "package-lock.json").is_file()


def test_render_blueprint_contains_no_literal_credentials_or_wildcard_hosts() -> None:
    source = (REPOSITORY_ROOT / "render.yaml").read_text(encoding="utf-8")
    blueprint = _blueprint()
    api_env = _environment(_service(blueprint, "growthloop-api"))

    assert "postgresql://" not in source
    assert "password:" not in source.lower()
    assert "*" not in str(api_env["MCP_ALLOWED_HOSTS"])
    assert "*" not in str(api_env["CORS_ORIGINS"])
    assert api_env["DATABASE_URL"].get("sync") is False
    assert api_env["OWNER_PASSWORD"].get("sync") is False


def test_backend_python_version_matches_project_runtime() -> None:
    assert (
        (REPOSITORY_ROOT / "backend" / ".python-version").read_text().strip()
        == "3.12.12"
    )
