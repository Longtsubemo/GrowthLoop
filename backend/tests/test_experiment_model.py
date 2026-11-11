"""Database-level tests for the Experiment model."""

import time
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.models import Experiment, ExperimentStatus

REQUIRED_FIELDS: dict[str, str] = {
    "title": "Landing page headline test",
    "hypothesis": "A benefit-led headline increases signups",
    "target_audience": "First-time visitors from Product Hunt",
    "channel": "landing_page",
    "success_metric": "Signup conversion rate",
}


def make_experiment(**overrides: object) -> Experiment:
    """Experiment with every required field set; pass overrides to vary."""
    values: dict[str, object] = dict(REQUIRED_FIELDS)
    values.update(overrides)
    return Experiment(**values)


def test_create_experiment_persists_all_fields(db_session) -> None:
    experiment = make_experiment(
        budget_amount=Decimal("15000.50"),
        currency_code="EUR",
        status=ExperimentStatus.RUNNING,
        execution_steps=[
            "Draft the variant headline",
            "Ship behind a feature flag",
            "Measure for two weeks",
        ],
        actual_result="Conversion improved by 12%",
    )
    db_session.add(experiment)
    db_session.commit()
    experiment_id = experiment.id

    db_session.expunge_all()
    stored = db_session.get(Experiment, experiment_id)

    assert stored is not None
    assert stored.id == experiment_id
    assert stored.title == "Landing page headline test"
    assert stored.hypothesis == "A benefit-led headline increases signups"
    assert stored.target_audience == "First-time visitors from Product Hunt"
    assert stored.channel == "landing_page"
    assert stored.budget_amount == Decimal("15000.50")
    assert stored.currency_code == "EUR"
    assert stored.status is ExperimentStatus.RUNNING
    assert stored.execution_steps == [
        "Draft the variant headline",
        "Ship behind a feature flag",
        "Measure for two weeks",
    ]
    assert stored.success_metric == "Signup conversion rate"
    assert stored.actual_result == "Conversion improved by 12%"


def test_id_is_a_generated_uuid(db_session) -> None:
    first = make_experiment()
    second = make_experiment()
    db_session.add_all([first, second])
    db_session.flush()

    assert isinstance(first.id, uuid.UUID)
    assert isinstance(second.id, uuid.UUID)
    assert first.id.version == 4
    assert first.id != second.id


def test_default_status_is_draft(db_session) -> None:
    experiment = make_experiment()
    db_session.add(experiment)
    db_session.commit()
    db_session.expire_all()

    assert experiment.status is ExperimentStatus.DRAFT


def test_default_currency_is_inr(db_session) -> None:
    experiment = make_experiment()
    db_session.add(experiment)
    db_session.commit()
    db_session.expire_all()

    assert experiment.currency_code == "INR"


def test_server_defaults_apply_without_the_orm(db_session) -> None:
    db_session.execute(sa.insert(Experiment).values(**REQUIRED_FIELDS))

    row = db_session.execute(sa.select(Experiment.__table__)).mappings().one()

    assert row["status"] == "draft"
    assert row["currency_code"] == "INR"
    assert row["execution_steps"] == []
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


@pytest.mark.parametrize("missing_field", sorted(REQUIRED_FIELDS))
def test_required_fields_reject_null(db_session, missing_field: str) -> None:
    values: dict[str, object] = {**REQUIRED_FIELDS, missing_field: None}
    db_session.add(Experiment(**values))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_optional_fields_accept_null(db_session) -> None:
    experiment = make_experiment(budget_amount=None, actual_result=None)
    db_session.add(experiment)
    db_session.commit()
    db_session.expire_all()

    assert experiment.budget_amount is None
    assert experiment.actual_result is None


def test_execution_steps_persist_in_order(db_session) -> None:
    steps = ["Step one", "Step two", "Step three"]
    experiment = make_experiment(execution_steps=steps)
    db_session.add(experiment)
    db_session.commit()
    experiment_id = experiment.id

    db_session.expunge_all()
    stored = db_session.get(Experiment, experiment_id)

    assert stored is not None
    assert stored.execution_steps == steps


def test_unknown_status_rejected_by_database(db_session) -> None:
    statement = sa.text(
        "INSERT INTO experiments "
        "(title, hypothesis, target_audience, channel, success_metric, status) "
        "VALUES ('t', 'h', 'a', 'c', 'm', 'bogus')"
    )

    with pytest.raises(IntegrityError):
        db_session.execute(statement)


def test_timestamps_are_set_and_updated(db_session) -> None:
    experiment = make_experiment()
    db_session.add(experiment)
    db_session.commit()
    db_session.expire_all()

    created_at = experiment.created_at
    assert created_at is not None
    assert created_at.tzinfo is not None
    assert experiment.updated_at is not None
    assert experiment.updated_at.tzinfo is not None

    time.sleep(0.05)
    experiment.title = "Updated headline"
    db_session.commit()
    db_session.expire_all()

    assert experiment.created_at == created_at
    assert experiment.updated_at > created_at
