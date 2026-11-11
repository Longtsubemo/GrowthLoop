"""Pydantic schemas for the Experiment domain.

Request schemas are strict (``extra="forbid"``) so clients cannot supply
unknown fields — in particular ``id``, ``created_at`` and ``updated_at``,
which are never client-writable. ``ExperimentUpdate`` distinguishes
omitted fields (left unchanged) from explicit ``null`` values (which
clear the optional fields).
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.models.experiment import ExperimentStatus

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Channel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
ExecutionStep = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
BudgetAmount = Annotated[
    Decimal, Field(ge=0, max_digits=12, decimal_places=2)
]

# ExperimentUpdate fields backed by NOT NULL columns: explicit null is
# rejected so clients must omit the field instead.
_REQUIRED_FIELDS = frozenset(
    {
        "title",
        "hypothesis",
        "target_audience",
        "channel",
        "currency_code",
        "execution_steps",
        "success_metric",
    }
)


class ExperimentCreate(BaseModel):
    """Payload for creating an experiment."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    hypothesis: NonEmptyText
    target_audience: NonEmptyText
    channel: Channel
    budget_amount: BudgetAmount | None = None
    currency_code: CurrencyCode = "INR"
    status: ExperimentStatus = ExperimentStatus.DRAFT
    execution_steps: list[ExecutionStep] = Field(default_factory=list)
    success_metric: NonEmptyText
    actual_result: NonEmptyText | None = None


class ExperimentUpdate(BaseModel):
    """Payload for partially updating an experiment.

    Omitted fields are left unchanged. Explicit ``null`` clears the
    optional fields (``budget_amount``, ``actual_result``) but is rejected
    for fields backed by NOT NULL columns. Status transitions use the
    dedicated ``PATCH .../status`` endpoint.
    """

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    hypothesis: NonEmptyText | None = None
    target_audience: NonEmptyText | None = None
    channel: Channel | None = None
    budget_amount: BudgetAmount | None = None
    currency_code: CurrencyCode | None = None
    execution_steps: list[ExecutionStep] | None = None
    success_metric: NonEmptyText | None = None
    actual_result: NonEmptyText | None = None

    @model_validator(mode="after")
    def _reject_null_for_required_fields(self) -> "ExperimentUpdate":
        for field_name in _REQUIRED_FIELDS & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(
                    f"'{field_name}' cannot be null; "
                    f"omit the field to leave it unchanged"
                )
        return self


class ExperimentStatusUpdate(BaseModel):
    """Payload for transitioning an experiment's status."""

    model_config = ConfigDict(extra="forbid")

    status: ExperimentStatus


class ExperimentResultUpdate(BaseModel):
    """Payload for recording an experiment's actual result."""

    model_config = ConfigDict(extra="forbid")

    actual_result: NonEmptyText


class ExperimentResponse(BaseModel):
    """Complete experiment representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    hypothesis: str
    target_audience: str
    channel: str
    budget_amount: Decimal | None
    currency_code: str
    status: ExperimentStatus
    execution_steps: list[str]
    success_metric: str
    actual_result: str | None
    created_at: datetime
    updated_at: datetime


class ExperimentListResponse(BaseModel):
    """One page of experiments plus pagination metadata."""

    items: list[ExperimentResponse]
    total: int
    limit: int
    offset: int
