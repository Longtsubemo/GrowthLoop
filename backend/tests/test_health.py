"""Tests for the health-check endpoint."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import health as health_module
from app.main import app
from app import main as main_module


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_ready_when_database_is_reachable(
    migrated_engine, monkeypatch
) -> None:
    factory = sessionmaker(bind=migrated_engine)
    monkeypatch.setattr(health_module, "SessionLocal", factory)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_returns_generic_unavailable_when_database_is_down(
    monkeypatch,
) -> None:
    engine = create_engine(
        "postgresql+psycopg://postgres:postgres@127.0.0.1:1/growthloop_unreachable",
        connect_args={"connect_timeout": 1},
    )
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(health_module, "SessionLocal", factory)

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health/ready")
    finally:
        engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
    assert "postgres" not in response.text.lower()
    assert "traceback" not in response.text.lower()


def test_liveness_stays_healthy_when_database_is_down(monkeypatch) -> None:
    def unavailable_session() -> None:
        raise AssertionError("liveness must not open a database session")

    monkeypatch.setattr(health_module, "SessionLocal", unavailable_session)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_application_disposes_shared_engine_on_shutdown(monkeypatch) -> None:
    class EngineSpy:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine_spy = EngineSpy()
    monkeypatch.setattr(main_module, "engine", engine_spy)
    application = main_module.create_app()

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert engine_spy.disposed is False

    assert engine_spy.disposed is True
