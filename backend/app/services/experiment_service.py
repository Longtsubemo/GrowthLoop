"""Business logic for experiments.

Both the FastAPI routers (``app.api``) and the MCP tools (``mcp_server``)
call these functions; neither implements experiment rules on its own.
Each function owns its transaction: it commits before returning and
leaves the session in a clean state for the caller.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Experiment, ExperimentStatus
from app.schemas.experiment import ExperimentCreate, ExperimentUpdate
from app.services.exceptions import ExperimentNotFoundError

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


class ExperimentPage(NamedTuple):
    """One page of experiments plus the total count of matching rows."""

    items: list[Experiment]
    total: int


def create_experiment(session: Session, data: ExperimentCreate) -> Experiment:
    """Persist a new experiment and return the stored record."""
    experiment = Experiment(**data.model_dump())
    session.add(experiment)
    session.commit()
    session.refresh(experiment)
    return experiment


def get_experiment(session: Session, experiment_id: uuid.UUID) -> Experiment:
    """Return one experiment by id; raise if it does not exist."""
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        raise ExperimentNotFoundError(experiment_id)
    return experiment


def list_experiments(
    session: Session,
    *,
    status: ExperimentStatus | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> ExperimentPage:
    """Return a page of experiments, newest first, and the total count.

    ``status`` filters the result; ``limit``/``offset`` paginate it.
    """
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")
    if offset < 0:
        raise ValueError("offset must be zero or greater")

    conditions = ()
    if status is not None:
        conditions = (Experiment.status == status,)

    count = session.scalar(
        select(func.count()).select_from(Experiment).where(*conditions)
    )
    items = list(
        session.scalars(
            select(Experiment)
            .where(*conditions)
            .order_by(Experiment.created_at.desc(), Experiment.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return ExperimentPage(items=items, total=count if count is not None else 0)


def update_experiment(
    session: Session, experiment_id: uuid.UUID, data: ExperimentUpdate
) -> Experiment:
    """Apply a partial update to an experiment.

    Omitted fields stay unchanged; explicit ``null`` clears optional
    fields. Raises ``ExperimentNotFoundError`` if the id does not exist.
    """
    experiment = get_experiment(session, experiment_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(experiment, field, value)
    session.commit()
    session.refresh(experiment)
    return experiment


def update_experiment_status(
    session: Session, experiment_id: uuid.UUID, status: ExperimentStatus
) -> Experiment:
    """Transition an experiment to a new status."""
    experiment = get_experiment(session, experiment_id)
    experiment.status = status
    session.commit()
    session.refresh(experiment)
    return experiment


def record_experiment_result(
    session: Session, experiment_id: uuid.UUID, actual_result: str
) -> Experiment:
    """Record what actually happened in an experiment."""
    experiment = get_experiment(session, experiment_id)
    experiment.actual_result = actual_result
    session.commit()
    session.refresh(experiment)
    return experiment


def delete_experiment(session: Session, experiment_id: uuid.UUID) -> None:
    """Delete an experiment; raise if it does not exist."""
    experiment = get_experiment(session, experiment_id)
    session.delete(experiment)
    session.commit()
