"""Integration tests for the experiment REST API.

Requests run through the FastAPI app with its database dependency
overridden onto the isolated test database (see ``conftest.py``); the
development database is never touched.

Note: ``Decimal`` fields (``budget_amount``) serialize as JSON strings,
e.g. ``"15000.50"``, to preserve precision.
"""

import uuid

import pytest

EXPERIMENTS_URL = "/api/v1/experiments"

VALID_CREATE: dict[str, object] = {
    "title": "Landing page headline test",
    "hypothesis": "A benefit-led headline increases signups",
    "target_audience": "First-time visitors from Product Hunt",
    "channel": "landing_page",
    "success_metric": "Signup conversion rate",
}

REQUIRED_FIELDS = ("title", "hypothesis", "target_audience", "channel", "success_metric")


def create_experiment(client, **overrides: object) -> dict:
    """POST a valid experiment and return the created resource."""
    response = client.post(EXPERIMENTS_URL, json={**VALID_CREATE, **overrides})
    assert response.status_code == 201
    return response.json()


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def test_create_returns_201_with_full_resource(api_client) -> None:
    payload = {
        **VALID_CREATE,
        "budget_amount": 15000.50,
        "currency_code": "EUR",
        "status": "running",
        "execution_steps": ["Draft variant", "Ship flag", "Measure"],
        "actual_result": "Conversion improved by 12%",
    }

    response = api_client.post(EXPERIMENTS_URL, json=payload)

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["title"] == payload["title"]
    assert body["hypothesis"] == payload["hypothesis"]
    assert body["target_audience"] == payload["target_audience"]
    assert body["channel"] == payload["channel"]
    assert body["budget_amount"] == "15000.50"
    assert body["currency_code"] == "EUR"
    assert body["status"] == "running"
    assert body["execution_steps"] == ["Draft variant", "Ship flag", "Measure"]
    assert body["success_metric"] == payload["success_metric"]
    assert body["actual_result"] == "Conversion improved by 12%"
    assert body["created_at"] is not None
    assert body["updated_at"] is not None


def test_create_applies_defaults(api_client) -> None:
    body = create_experiment(api_client)

    assert body["status"] == "draft"
    assert body["currency_code"] == "INR"
    assert body["execution_steps"] == []
    assert body["budget_amount"] is None
    assert body["actual_result"] is None


def test_create_persists_the_experiment(api_client) -> None:
    body = create_experiment(api_client)

    stored = api_client.get(f"{EXPERIMENTS_URL}/{body['id']}")
    assert stored.status_code == 200
    assert stored.json()["title"] == body["title"]


@pytest.mark.parametrize("missing_field", REQUIRED_FIELDS)
def test_create_missing_required_field_is_rejected(
    api_client, missing_field: str
) -> None:
    payload = {k: v for k, v in VALID_CREATE.items() if k != missing_field}

    response = api_client.post(EXPERIMENTS_URL, json=payload)

    assert response.status_code == 422


def test_create_rejects_negative_budget(api_client) -> None:
    response = api_client.post(
        EXPERIMENTS_URL, json={**VALID_CREATE, "budget_amount": -10}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "budget", [15000.505, 1234567890123.00, "not-a-number"]
)
def test_create_rejects_malformed_budget(api_client, budget: object) -> None:
    response = api_client.post(EXPERIMENTS_URL, json={**VALID_CREATE, "budget_amount": budget})

    assert response.status_code == 422


@pytest.mark.parametrize("currency", ["inr", "EU", "EURO", "US$", ""])
def test_create_rejects_invalid_currency(api_client, currency: str) -> None:
    response = api_client.post(
        EXPERIMENTS_URL, json={**VALID_CREATE, "currency_code": currency}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "steps", [["Draft", ""], ["  "], ["Draft", 3], "not-a-list"]
)
def test_create_rejects_invalid_execution_steps(api_client, steps: object) -> None:
    response = api_client.post(
        EXPERIMENTS_URL, json={**VALID_CREATE, "execution_steps": steps}
    )

    assert response.status_code == 422


def test_create_allows_empty_execution_steps(api_client) -> None:
    body = create_experiment(api_client, execution_steps=[])

    assert body["execution_steps"] == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"channel": "x" * 51},
        {"hypothesis": "  "},
    ],
)
def test_create_rejects_invalid_strings(api_client, overrides: dict) -> None:
    response = api_client.post(EXPERIMENTS_URL, json={**VALID_CREATE, **overrides})

    assert response.status_code == 422


def test_create_rejects_unknown_status(api_client) -> None:
    response = api_client.post(
        EXPERIMENTS_URL, json={**VALID_CREATE, "status": "bogus"}
    )

    assert response.status_code == 422


def test_create_rejects_protected_fields(api_client) -> None:
    payload = {
        **VALID_CREATE,
        "id": str(uuid.uuid4()),
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
    }

    response = api_client.post(EXPERIMENTS_URL, json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_get_returns_stored_experiment(api_client) -> None:
    created = create_experiment(api_client, budget_amount=2500)

    response = api_client.get(f"{EXPERIMENTS_URL}/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["budget_amount"] == "2500.00"
    assert body["title"] == VALID_CREATE["title"]


def test_get_unknown_uuid_returns_404(api_client) -> None:
    response = api_client.get(f"{EXPERIMENTS_URL}/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_malformed_uuid_returns_422(api_client) -> None:
    response = api_client.get(f"{EXPERIMENTS_URL}/not-a-uuid")

    assert response.status_code == 422


def test_list_returns_experiments_newest_first(api_client) -> None:
    first = create_experiment(api_client, title="First")
    second = create_experiment(api_client, title="Second")
    third = create_experiment(api_client, title="Third")

    response = api_client.get(EXPERIMENTS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["title"] for item in body["items"]] == [
        third["title"],
        second["title"],
        first["title"],
    ]
    timestamps = [item["created_at"] for item in body["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_list_paginates(api_client) -> None:
    created = [create_experiment(api_client, title=f"Exp {i}") for i in range(5)]

    page_one = api_client.get(EXPERIMENTS_URL, params={"limit": 2})
    assert page_one.status_code == 200
    body = page_one.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [item["title"] for item in body["items"]] == [
        created[4]["title"],
        created[3]["title"],
    ]

    page_two = api_client.get(EXPERIMENTS_URL, params={"limit": 2, "offset": 2})
    assert [item["title"] for item in page_two.json()["items"]] == [
        created[2]["title"],
        created[1]["title"],
    ]

    page_three = api_client.get(EXPERIMENTS_URL, params={"limit": 2, "offset": 4})
    assert [item["title"] for item in page_three.json()["items"]] == [
        created[0]["title"]
    ]

    beyond = api_client.get(EXPERIMENTS_URL, params={"limit": 2, "offset": 6})
    assert beyond.json()["items"] == []
    assert beyond.json()["total"] == 5


def test_list_reports_default_pagination(api_client) -> None:
    create_experiment(api_client)

    response = api_client.get(EXPERIMENTS_URL)

    body = response.json()
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["total"] == 1
    assert len(body["items"]) == 1


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_rejects_invalid_pagination(api_client, query: dict) -> None:
    response = api_client.get(EXPERIMENTS_URL, params=query)

    assert response.status_code == 422


def test_list_filters_by_status(api_client) -> None:
    create_experiment(api_client, title="Draft one")
    create_experiment(api_client, title="Running one", status="running")
    create_experiment(api_client, title="Running two", status="running")
    create_experiment(api_client, title="Completed one", status="completed")

    response = api_client.get(EXPERIMENTS_URL, params={"status": "running"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["title"] for item in body["items"]} == {
        "Running one",
        "Running two",
    }


def test_list_rejects_invalid_status_filter(api_client) -> None:
    response = api_client.get(EXPERIMENTS_URL, params={"status": "bogus"})

    assert response.status_code == 422


def test_list_returns_empty_when_no_experiments(api_client) -> None:
    response = api_client.get(EXPERIMENTS_URL)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


# ---------------------------------------------------------------------------
# Updates
# ---------------------------------------------------------------------------


def test_partial_update_changes_only_supplied_fields(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}", json={"title": "New headline"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New headline"
    assert body["hypothesis"] == created["hypothesis"]
    assert body["channel"] == created["channel"]
    assert body["success_metric"] == created["success_metric"]
    assert body["status"] == "draft"


def test_update_multiple_fields_together(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}",
        json={
            "title": "New headline",
            "channel": "cold_email",
            "execution_steps": ["Rewrite", "Resend"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New headline"
    assert body["channel"] == "cold_email"
    assert body["execution_steps"] == ["Rewrite", "Resend"]


def test_update_explicit_null_clears_optional_fields(api_client) -> None:
    created = create_experiment(
        api_client, budget_amount=5000, actual_result="Improved 5%"
    )

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}",
        json={"budget_amount": None, "actual_result": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["budget_amount"] is None
    assert body["actual_result"] is None


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "hypothesis",
        "target_audience",
        "channel",
        "currency_code",
        "execution_steps",
        "success_metric",
    ],
)
def test_update_null_on_required_field_is_rejected(
    api_client, field: str
) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}", json={field: None}
    )

    assert response.status_code == 422


def test_update_rejects_protected_fields(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}",
        json={
            "id": str(uuid.uuid4()),
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 422
    unchanged = api_client.get(f"{EXPERIMENTS_URL}/{created['id']}")
    assert unchanged.json()["id"] == created["id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"budget_amount": -1},
        {"currency_code": "eur"},
        {"title": ""},
        {"execution_steps": ["ok", ""]},
    ],
)
def test_update_rejects_invalid_values(api_client, overrides: dict) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}", json=overrides
    )

    assert response.status_code == 422


def test_update_unknown_experiment_returns_404(api_client) -> None:
    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{uuid.uuid4()}", json={"title": "New headline"}
    )

    assert response.status_code == 404


def test_empty_update_leaves_resource_and_updated_at_unchanged(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(f"{EXPERIMENTS_URL}/{created['id']}", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == created["title"]
    assert body["updated_at"] == created["updated_at"]


def test_update_advances_updated_at_but_not_created_at(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}", json={"title": "New headline"}
    )

    body = response.json()
    assert body["created_at"] == created["created_at"]
    assert body["updated_at"] > created["updated_at"]


def test_status_change(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}/status", json={"status": "running"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["updated_at"] > body["created_at"]


def test_status_change_rejects_invalid_value(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}/status", json={"status": "bogus"}
    )

    assert response.status_code == 422


def test_status_change_unknown_experiment_returns_404(api_client) -> None:
    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{uuid.uuid4()}/status", json={"status": "running"}
    )

    assert response.status_code == 404


def test_record_result(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}/result",
        json={"actual_result": "Conversion improved by 12%"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["actual_result"] == "Conversion improved by 12%"
    assert body["status"] == "draft"


def test_record_result_rejects_empty_text(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{created['id']}/result", json={"actual_result": "  "}
    )

    assert response.status_code == 422


def test_record_result_unknown_experiment_returns_404(api_client) -> None:
    response = api_client.patch(
        f"{EXPERIMENTS_URL}/{uuid.uuid4()}/result",
        json={"actual_result": "Anything"},
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_delete_removes_experiment(api_client) -> None:
    created = create_experiment(api_client)

    response = api_client.delete(f"{EXPERIMENTS_URL}/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert api_client.get(f"{EXPERIMENTS_URL}/{created['id']}").status_code == 404
    listing = api_client.get(EXPERIMENTS_URL)
    assert listing.json()["total"] == 0


def test_delete_unknown_experiment_returns_404(api_client) -> None:
    response = api_client.delete(f"{EXPERIMENTS_URL}/{uuid.uuid4()}")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def test_budget_amount_round_trips_exact_decimals(api_client) -> None:
    body = create_experiment(api_client, budget_amount="9999999999.99")

    assert body["budget_amount"] == "9999999999.99"
