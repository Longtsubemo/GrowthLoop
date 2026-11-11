"""Experiment database model."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExperimentStatus(StrEnum):
    """Lifecycle states of a growth experiment."""

    DRAFT = "draft"
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class Experiment(Base):
    """A single growth experiment managed through GrowthLoop.

    ``status`` is stored as a ``VARCHAR`` plus a ``CHECK`` constraint
    (non-native enum) so adding a new state later is a simple migration
    rather than a PostgreSQL ``ALTER TYPE`` dance.
    """

    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint(
            "char_length(currency_code) = 3",
            name="ck_experiments_currency_code_length",
        ),
        Index("ix_experiments_status", "status"),
        Index("ix_experiments_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    target_audience: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    budget_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default="INR"
    )
    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(
            ExperimentStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda cls: [member.value for member in cls],
            length=16,
            name="experiment_status",
        ),
        nullable=False,
        default=ExperimentStatus.DRAFT,
        server_default="draft",
    )
    # Ordered list of free-text steps; JSONB is justified because steps are
    # stored and retrieved as a whole ordered document, never joined on or
    # queried per-element.
    execution_steps: Mapped[list[str]] = mapped_column(
        postgresql.JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    success_metric: Mapped[str] = mapped_column(Text, nullable=False)
    actual_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Experiment id={self.id} title={self.title!r} status={self.status}>"
