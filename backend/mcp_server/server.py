"""GrowthLoop MCP server: experiment management tools over stdio.

Every tool is a thin wrapper around the shared business logic in
``app.services.experiment_service`` — the same functions the REST API
calls. This module implements no business rules of its own: tool input
schemas are derived from the shared Pydantic aliases in
``app.schemas.experiment``, arguments are validated through the shared
``ExperimentCreate``/``ExperimentUpdate`` models, and persistence goes
through the shared ``SessionLocal`` factory (one short database
session per tool invocation).

The server speaks MCP over stdio (``mcp.run()``). stdout carries only
protocol messages; diagnostics go to stderr via the SDK's logging.

Note: this uses the Python MCP SDK v2 API, where the v1 ``FastMCP`` was
renamed to ``MCPServer`` (``from mcp.server.mcpserver import MCPServer``).
"""

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, TypeVar
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError
from pydantic.json_schema import PydanticJsonSchemaWarning
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Experiment
from app.models.experiment import ExperimentStatus
from app.schemas.experiment import (
    BudgetAmount,
    Channel,
    CurrencyCode,
    ExecutionStep,
    ExperimentCreate,
    ExperimentResponse,
    ExperimentUpdate,
    NonEmptyText,
    Title,
)
from app.services import experiment_service
from app.services.exceptions import ExperimentNotFoundError

ModelT = TypeVar("ModelT", bound=BaseModel)

# Sentinel marking tool arguments the caller omitted. The SDK fills
# argument defaults before the tool function runs, so a ``None`` default
# cannot distinguish "field absent" from "field explicitly null";
# omitted ``update_experiment`` fields therefore carry this marker.
_UNSET: Any = object()

mcp = MCPServer(
    "growthloop",
    version="0.1.0",
    instructions=(
        "Manage growth experiments: create them, list and fetch them, "
        "update their fields and lifecycle status, record their actual "
        "results, and delete them. Every change is persisted to "
        "PostgreSQL immediately and is visible in the GrowthLoop "
        "dashboard."
    ),
)


def _serialize(experiment: Experiment) -> dict[str, Any]:
    """Render an experiment exactly as the REST API returns it."""
    return ExperimentResponse.model_validate(experiment).model_dump(mode="json")


def _validation_message(exc: ValidationError) -> str:
    """Summarize a validation failure without echoing raw input values."""
    parts = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or "payload"
        parts.append(f"{field}: {error['msg']}")
    return "; ".join(parts)


def _validated(model: type[ModelT], payload: dict[str, Any]) -> ModelT:
    """Validate a payload with a shared schema, raising a clean tool error."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ToolError(_validation_message(exc)) from exc


@contextmanager
def _session() -> Iterator[Session]:
    """Yield a database session for a single tool invocation.

    Sessions come from the shared ``SessionLocal`` factory and are always
    closed when the tool call ends. Domain errors surface as clean tool
    errors; anything unexpected stays generic — the SDK logs the details
    server-side and shows the client no internals.
    """
    with SessionLocal() as session:
        try:
            yield session
        except ExperimentNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        except SQLAlchemyError as exc:
            # A database outage is an operational failure, not a bug in the
            # caller's arguments. Translate it into a controlled tool error so
            # clients never receive SQL, credentials or a stack trace.
            raise ToolError(
                "The database is unavailable. Please try again."
            ) from exc


def create_experiment(
    title: Title,
    hypothesis: NonEmptyText,
    target_audience: NonEmptyText,
    channel: Channel,
    success_metric: NonEmptyText,
    budget_amount: BudgetAmount | None = None,
    currency_code: CurrencyCode = "INR",
    status: ExperimentStatus = ExperimentStatus.DRAFT,
    execution_steps: list[ExecutionStep] | None = None,
    actual_result: NonEmptyText | None = None,
) -> dict[str, Any]:
    """Create a new growth experiment and persist it to PostgreSQL.

    Returns the stored experiment, including its generated id and
    timestamps. Defaults: status "draft", currency INR, no budget, no
    result, no execution steps.
    """
    payload = _validated(
        ExperimentCreate,
        {
            "title": title,
            "hypothesis": hypothesis,
            "target_audience": target_audience,
            "channel": channel,
            "success_metric": success_metric,
            "budget_amount": budget_amount,
            "currency_code": currency_code,
            "status": status,
            "execution_steps": execution_steps or [],
            "actual_result": actual_result,
        },
    )
    with _session() as session:
        experiment = experiment_service.create_experiment(session, payload)
        return _serialize(experiment)


def list_experiments(
    status: ExperimentStatus | None = None,
    limit: Annotated[
        int, Field(ge=1, le=experiment_service.MAX_PAGE_LIMIT)
    ] = experiment_service.DEFAULT_PAGE_LIMIT,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    """List experiments, newest first.

    Optionally filter by status and paginate: limit must be between 1
    and 100 (default 20), offset is zero-based (default 0). Returns the
    matching items plus the total count and the limit/offset applied.
    """
    with _session() as session:
        page = experiment_service.list_experiments(
            session, status=status, limit=limit, offset=offset
        )
        items = [_serialize(experiment) for experiment in page.items]
    return {"items": items, "total": page.total, "limit": limit, "offset": offset}


def get_experiment(experiment_id: UUID) -> dict[str, Any]:
    """Fetch a single experiment by its UUID."""
    with _session() as session:
        experiment = experiment_service.get_experiment(session, experiment_id)
        return _serialize(experiment)


def update_experiment(
    experiment_id: UUID,
    title: Title | None = _UNSET,
    hypothesis: NonEmptyText | None = _UNSET,
    target_audience: NonEmptyText | None = _UNSET,
    channel: Channel | None = _UNSET,
    success_metric: NonEmptyText | None = _UNSET,
    budget_amount: BudgetAmount | None = _UNSET,
    currency_code: CurrencyCode | None = _UNSET,
    execution_steps: list[ExecutionStep] | None = _UNSET,
    actual_result: NonEmptyText | None = _UNSET,
) -> dict[str, Any]:
    """Partially update an experiment by its UUID.

    Only the arguments actually provided are changed; omitted fields
    keep their current value. An explicit null clears the optional
    fields budget_amount and actual_result, but is rejected for required
    fields. To change the lifecycle status, call
    update_experiment_status instead.
    """
    provided: dict[str, Any] = {
        "title": title,
        "hypothesis": hypothesis,
        "target_audience": target_audience,
        "channel": channel,
        "success_metric": success_metric,
        "budget_amount": budget_amount,
        "currency_code": currency_code,
        "execution_steps": execution_steps,
        "actual_result": actual_result,
    }
    changes = {
        field: value for field, value in provided.items() if value is not _UNSET
    }
    payload = _validated(ExperimentUpdate, changes)
    with _session() as session:
        experiment = experiment_service.update_experiment(
            session, experiment_id, payload
        )
        return _serialize(experiment)


def update_experiment_status(
    experiment_id: UUID, status: ExperimentStatus
) -> dict[str, Any]:
    """Transition an experiment to a new lifecycle status.

    Valid statuses: draft, planned, running, completed, paused,
    cancelled.
    """
    with _session() as session:
        experiment = experiment_service.update_experiment_status(
            session, experiment_id, status
        )
        return _serialize(experiment)


def record_experiment_result(
    experiment_id: UUID, actual_result: NonEmptyText
) -> dict[str, Any]:
    """Record the actual outcome of running an experiment."""
    with _session() as session:
        experiment = experiment_service.record_experiment_result(
            session, experiment_id, actual_result
        )
        return _serialize(experiment)


def delete_experiment(experiment_id: UUID) -> dict[str, Any]:
    """Permanently delete an experiment from PostgreSQL.

    Destructive: the experiment record and all of its data are removed
    and cannot be recovered. Only call this tool when the user has
    explicitly confirmed the deletion.
    """
    with _session() as session:
        experiment_service.delete_experiment(session, experiment_id)
    return {"deleted": True, "experiment_id": str(experiment_id)}


def _register_tools() -> None:
    """Register the seven experiment tools on the MCP server."""
    with warnings.catch_warnings():
        # update_experiment marks omitted fields with a non-JSON sentinel
        # default. Pydantic warns that the sentinel cannot be rendered in
        # the published JSON schema and excludes it — exactly the schema
        # we want (optional field, no advertised default) — so the
        # warning is expected and suppressed here.
        warnings.simplefilter("ignore", PydanticJsonSchemaWarning)
        mcp.add_tool(create_experiment)
        mcp.add_tool(
            list_experiments, annotations=ToolAnnotations(readOnlyHint=True)
        )
        mcp.add_tool(get_experiment, annotations=ToolAnnotations(readOnlyHint=True))
        mcp.add_tool(update_experiment)
        mcp.add_tool(update_experiment_status)
        mcp.add_tool(record_experiment_result)
        mcp.add_tool(
            delete_experiment, annotations=ToolAnnotations(destructiveHint=True)
        )


_register_tools()


def main() -> None:
    """Run the MCP server over stdio (for Claude Desktop)."""
    mcp.run()


if __name__ == "__main__":
    main()
