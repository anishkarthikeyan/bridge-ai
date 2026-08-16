"""GET /dashboard/summary tests (Phase 6.5 Part 12) — same dependency-override pattern as
test_api_cases.py: an in-memory FakeCaseRepository, no real database needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.entities.case import Case
from app.domain.entities.decision import Decision
from app.domain.value_objects.communication_health import CommunicationHealth
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_state import ResolutionState
from app.integrations.api.dependencies import get_case_repository
from app.main import create_app
from tests.unit.brain.fakes import FakeCaseRepository

# The dashboard router computes "due" against the real wall clock (datetime.now(UTC)), not an
# injectable one — these are picked far enough in the past/future to be unambiguous regardless
# of when this test actually runs.
_DEFINITELY_PAST = datetime(2000, 1, 1, tzinfo=UTC)
_DEFINITELY_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


def _client_with_repo(repo: FakeCaseRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_case_repository] = lambda: repo
    return TestClient(app)


def test_dashboard_summary_aggregates_across_cases() -> None:
    repo = FakeCaseRepository()

    critical_case = repo.add(
        Case(
            id=uuid4(),
            topic="payment_system",
            priority=Priority.HIGH,
            communication_health=CommunicationHealth.CRITICAL,
            resolution_status=ResolutionState.OPEN,
            attempt_count=1,
            next_check_at=_DEFINITELY_PAST,  # due
        )
    )
    repo.add_decision(
        critical_case.id,
        Decision(
            id=uuid4(),
            case_id=critical_case.id,
            node_name="escalate",
            reasoning_summary="Escalating.",
            status=DecisionStatus.SUCCESS,
            created_at=_DEFINITELY_PAST,
        ),
    )

    repo.add(
        Case(
            id=uuid4(),
            topic="database_migration",
            priority=Priority.MEDIUM,
            communication_health=CommunicationHealth.HEALTHY,
            resolution_status=ResolutionState.OPEN,
            attempt_count=1,
            next_check_at=_DEFINITELY_FUTURE,  # not due yet
        )
    )
    repo.add(
        Case(
            id=uuid4(),
            topic="payment_system",
            priority=Priority.LOW,
            communication_health=CommunicationHealth.HEALTHY,
            resolution_status=ResolutionState.RESOLVED,
            attempt_count=1,
        )
    )

    client = _client_with_repo(repo)
    response = client.get("/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_open_cases"] == 2
    assert body["total_resolved_cases"] == 1
    assert body["critical_cases"] == 1
    assert body["high_priority_cases"] == 1
    assert body["medium_priority_cases"] == 1
    assert body["low_priority_cases"] == 0  # the low-priority case is resolved, not open
    assert body["cases_waiting_for_reply"] == 2
    assert body["cases_due_for_followup"] == 1
    assert body["cases_escalated"] == 1
    assert len(body["recent_decisions"]) == 1
    assert body["recent_decisions"][0]["node_name"] == "escalate"
    assert body["recent_decisions"][0]["case_id"] == str(critical_case.id)


def test_dashboard_summary_on_an_empty_repository() -> None:
    client = _client_with_repo(FakeCaseRepository())

    response = client.get("/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_open_cases"] == 0
    assert body["recent_decisions"] == []
