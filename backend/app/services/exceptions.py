"""Domain exceptions raised by the shared services.

Services never depend on FastAPI or the MCP SDK; callers translate these
exceptions into transport-appropriate responses (HTTP 404, MCP tool
errors).
"""

import uuid


class ServiceError(Exception):
    """Base class for errors raised by the service layer."""


class ExperimentNotFoundError(ServiceError):
    """An operation targeted an experiment that does not exist."""

    def __init__(self, experiment_id: uuid.UUID) -> None:
        self.experiment_id = experiment_id
        super().__init__(f"Experiment {experiment_id} not found")
