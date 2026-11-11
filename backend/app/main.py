"""FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.experiments import experiments_router
from app.api.health import health_router
from app.core.config import get_settings
from app.services.exceptions import ExperimentNotFoundError


async def experiment_not_found_handler(
    request: Request, exc: ExperimentNotFoundError
) -> JSONResponse:
    """Translate the domain-level error into an HTTP 404 response."""
    return JSONResponse(
        status_code=404,
        content={"detail": f"Experiment {exc.experiment_id} not found"},
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    # The dashboard runs in the browser on a different origin than the API,
    # so cross-origin requests need CORS. Origins are configured through
    # the CORS_ORIGINS env var (comma-separated).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in settings.cors_origins.split(",")
            if origin.strip()
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(experiments_router)
    app.add_exception_handler(ExperimentNotFoundError, experiment_not_found_handler)
    return app


app = create_app()
