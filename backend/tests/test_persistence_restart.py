"""Persistence across real FastAPI restarts and MCP process reconnects.

These tests start the backend as a genuine uvicorn subprocess against the
isolated pytest database (never the development database), stop it, start
a new process, and verify the record is still there. A fresh MCP stdio
subprocess then reads and deletes the same record.

Run with ``pytest tests/test_persistence_restart.py``.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import sqlalchemy as sa
from mcp import Client, StdioServerParameters
from sqlalchemy.engine import Engine

from app.models import Experiment

BACKEND_DIR = Path(__file__).resolve().parent.parent
EXPERIMENTS_URL = "/api/v1/experiments"


def _free_port() -> int:
    """Reserve a localhost port by binding to port 0 and releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(origin: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = (
                process.stderr.read().decode(errors="replace")
                if process.stderr is not None
                else ""
            )
            raise AssertionError(f"uvicorn exited before becoming healthy:\n{stderr}")
        try:
            response = httpx.get(f"{origin}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError(f"uvicorn at {origin} did not become healthy in 30s")


def _authenticate_http_client(client: httpx.Client) -> None:
    """Login to one fresh backend process and retain its cookie and CSRF token."""
    login = client.post(
        "/api/v1/auth/login",
        json={"password": os.environ["OWNER_PASSWORD"]},
        headers={"Origin": "http://localhost:5173"},
    )
    assert login.status_code == 200, login.text
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]


@contextmanager
def running_backend(database_url: str) -> Iterator[str]:
    """Start uvicorn against ``database_url``; yield its origin; stop it."""
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_health(origin, process)
        yield origin
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


async def _mcp_get_and_delete(
    database_url: str, experiment_id: str, expected_title: str
) -> None:
    """Reconnect with a brand-new MCP stdio process and delete the row."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
    )
    async with Client(parameters, read_timeout_seconds=60) as client:
        fetched = await client.call_tool(
            "get_experiment", {"experiment_id": experiment_id}
        )
        assert not fetched.is_error, (
            fetched.content[0].text if fetched.content else "get failed"
        )
        assert fetched.structured_content["title"] == expected_title

        deleted = await client.call_tool(
            "delete_experiment", {"experiment_id": experiment_id}
        )
        assert not deleted.is_error, (
            deleted.content[0].text if deleted.content else "delete failed"
        )
        assert deleted.structured_content["deleted"] is True


def test_record_survives_backend_restart_and_mcp_reconnect(
    migrated_engine: Engine,
) -> None:
    database_url = migrated_engine.url.render_as_string(hide_password=False)
    payload = {
        "title": "Persistence across restarts",
        "hypothesis": "PostgreSQL keeps the row after the API process restarts",
        "target_audience": "Founders evaluating GrowthLoop",
        "channel": "email",
        "success_metric": "Signups per week",
        "budget_amount": "4321.99",
        "currency_code": "EUR",
        "execution_steps": ["Create", "Restart", "Verify"],
    }

    try:
        # First process: create the record, then shut the process down.
        with running_backend(database_url) as origin:
            with httpx.Client(base_url=origin, timeout=10) as client:
                _authenticate_http_client(client)
                response = client.post(EXPERIMENTS_URL, json=payload)
                assert response.status_code == 201, response.text
                created = response.json()

        # Second process: the same record must still be there.
        with running_backend(database_url) as origin:
            with httpx.Client(base_url=origin, timeout=10) as client:
                _authenticate_http_client(client)
                fetched = client.get(f"{EXPERIMENTS_URL}/{created['id']}")
                assert fetched.status_code == 200, fetched.text
                body = fetched.json()
                assert body["id"] == created["id"]
                assert body["title"] == payload["title"]
                assert body["budget_amount"] == "4321.99"
                assert body["execution_steps"] == ["Create", "Restart", "Verify"]
                assert body["created_at"] == created["created_at"]

                # A brand-new MCP stdio process reads and deletes the same row.
                asyncio.run(
                    _mcp_get_and_delete(
                        database_url, created["id"], payload["title"]
                    )
                )

                gone = client.get(f"{EXPERIMENTS_URL}/{created['id']}")
                assert gone.status_code == 404
    finally:
        with migrated_engine.begin() as connection:
            connection.execute(sa.delete(Experiment))
