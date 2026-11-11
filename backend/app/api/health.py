"""Health-check endpoint."""

from fastapi import APIRouter

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
def health_check() -> dict[str, str]:
    """Report service liveness."""
    return {"status": "ok"}
