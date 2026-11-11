"""Experiment REST endpoints.

Thin routers: validation happens in the Pydantic schemas, persistence
and business rules in ``app.services.experiment_service``.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.models import Experiment, ExperimentStatus
from app.schemas.experiment import (
    ExperimentCreate,
    ExperimentListResponse,
    ExperimentResponse,
    ExperimentResultUpdate,
    ExperimentStatusUpdate,
    ExperimentUpdate,
)
from app.services import experiment_service

experiments_router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


@experiments_router.post(
    "",
    response_model=ExperimentResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def create_experiment(
    payload: ExperimentCreate, session: Session = Depends(get_db_session)
) -> Experiment:
    """Create a new experiment."""
    return experiment_service.create_experiment(session, payload)


@experiments_router.get("", response_model=ExperimentListResponse)
def list_experiments(
    status: ExperimentStatus | None = None,
    limit: int = Query(
        default=experiment_service.DEFAULT_PAGE_LIMIT,
        ge=1,
        le=experiment_service.MAX_PAGE_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
) -> ExperimentListResponse:
    """List experiments, newest first, with optional status filter and pagination."""
    page = experiment_service.list_experiments(
        session, status=status, limit=limit, offset=offset
    )
    return ExperimentListResponse(
        items=page.items, total=page.total, limit=limit, offset=offset
    )


@experiments_router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(
    experiment_id: uuid.UUID, session: Session = Depends(get_db_session)
) -> Experiment:
    """Retrieve one experiment by id."""
    return experiment_service.get_experiment(session, experiment_id)


@experiments_router.patch("/{experiment_id}", response_model=ExperimentResponse)
def update_experiment(
    experiment_id: uuid.UUID,
    payload: ExperimentUpdate,
    session: Session = Depends(get_db_session),
) -> Experiment:
    """Partially update an experiment."""
    return experiment_service.update_experiment(session, experiment_id, payload)


@experiments_router.patch(
    "/{experiment_id}/status", response_model=ExperimentResponse
)
def update_experiment_status(
    experiment_id: uuid.UUID,
    payload: ExperimentStatusUpdate,
    session: Session = Depends(get_db_session),
) -> Experiment:
    """Transition an experiment to a new status."""
    return experiment_service.update_experiment_status(
        session, experiment_id, payload.status
    )


@experiments_router.patch(
    "/{experiment_id}/result", response_model=ExperimentResponse
)
def record_experiment_result(
    experiment_id: uuid.UUID,
    payload: ExperimentResultUpdate,
    session: Session = Depends(get_db_session),
) -> Experiment:
    """Record the actual result of an experiment."""
    return experiment_service.record_experiment_result(
        session, experiment_id, payload.actual_result
    )


@experiments_router.delete(
    "/{experiment_id}", status_code=http_status.HTTP_204_NO_CONTENT
)
def delete_experiment(
    experiment_id: uuid.UUID, session: Session = Depends(get_db_session)
) -> None:
    """Delete an experiment."""
    experiment_service.delete_experiment(session, experiment_id)
