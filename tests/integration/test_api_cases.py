"""Tests for the read-only case APIs (Phase 6.5 Part 11) — GET /cases, GET /cases/{id}, GET
/cases/{id}/timeline, GET /cases/{id}/decisions, plus pagination/filtering and error handling
(Part 13). The `CaseRepositoryPort` dependency is overridden with an in-memory
`FakeCaseRepository` (no real database needed here — the real SQLAlchemy implementation of
`list_cases`/`list_due_for_followup` is covered separately, against a real Postgres, by
tests/integration/test_case_repository.py) so these tests only exercise routing, DTO mapping,
filtering/validation, and error handling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.domain.entities.case import Case
from app.domain.entities.conversation import Conversation
from app.domain.entities.decision import Decision
from app.domain.entities.message import Message
from app.domain.entities.participant import Participant
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.communication_health import CommunicationHealth
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.message_direction import MessageDirection
from app.domain.value_objects.participant_source import ParticipantSource
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_state import ResolutionState
from app.integrations.api.dependencies import get_case_repository
from app.main import create_app
from tests.unit.brain.fakes import FakeCaseRepository


def _seeded_case(repo: FakeCaseRepository, **overrides) -> Case:
    defaults = {
        "id": uuid4(),
        "topic": "payment_system",
        "required_roles": ["Finance", "Security", "Support"],
        "missing_roles": ["Security", "Support"],
        "channels_used": [Channel.EMAIL],
        "communication_health": CommunicationHealth.AT_RISK,
        "resolution_status": ResolutionState.OPEN,
        "priority": Priority.HIGH,
        "attempt_count": 1,
        "created_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 1, 9, 30, tzinfo=UTC),
    }
    defaults.update(overrides)
    case = repo.add(Case(**defaults))

    participant = Participant(
        id=uuid4(),
        case_id=case.id,
        name="Dana Kapoor",
        role="Engineer",
        email="dana@co.com",
        source=ParticipantSource.EXPLICIT,
    )
    repo.add_participant(case.id, participant)

    conversation = Conversation(
        id=uuid4(), case_id=case.id, channel=Channel.EMAIL, external_thread_ref="t-1"
    )
    repo.add_conversation(case.id, conversation)
    conversation.messages.append(
        Message(
            id=uuid4(),
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND,
            content="Wanted Finance looped in before this ships.",
            sender_participant_id=participant.id,
            sent_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        )
    )

    decision = Decision(
        id=uuid4(),
        case_id=case.id,
        node_name="classify_topic",
        reasoning_summary="LLM classified topic as 'payment_system'.",
        chosen_action={"topic": "payment_system"},
        confidence=0.95,
        status=DecisionStatus.SUCCESS,
        created_at=datetime(2026, 8, 1, 9, 0, 5, tzinfo=UTC),
    )
    repo.add_decision(case.id, decision)

    pending_decision = Decision(
        id=uuid4(),
        case_id=case.id,
        node_name="create_decision",
        reasoning_summary="Decided to send an email to John Ortiz.",
        chosen_action={"channel": "email", "recipient_name": "John Ortiz"},
        status=DecisionStatus.PENDING,
        created_at=datetime(2026, 8, 1, 9, 0, 6, tzinfo=UTC),
    )
    repo.add_decision(case.id, pending_decision)

    return repo.get_by_id(case.id)


def _client_with_repo(repo: FakeCaseRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_case_repository] = lambda: repo
    return TestClient(app)


def test_get_health_still_works_without_a_database() -> None:
    # Smoke check that adding routers/DI didn't disturb the existing Phase 6 health endpoint.
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_cases_returns_paginated_dtos() -> None:
    repo = FakeCaseRepository()
    _seeded_case(repo)
    _seeded_case(repo, topic="database_migration", priority=Priority.MEDIUM)
    client = _client_with_repo(repo)

    response = client.get("/cases")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert {
        "id",
        "topic",
        "priority",
        "resolution_status",
        "communication_health",
        "missing_roles",
        "attempt_count",
        "next_check_at",
        "created_at",
        "updated_at",
    } <= set(body["items"][0].keys())


def test_list_cases_pagination_limit_and_offset() -> None:
    repo = FakeCaseRepository()
    for _ in range(5):
        _seeded_case(repo)
    client = _client_with_repo(repo)

    response = client.get("/cases", params={"limit": 2, "offset": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 2


def test_list_cases_filters_by_topic() -> None:
    repo = FakeCaseRepository()
    _seeded_case(repo, topic="payment_system")
    _seeded_case(repo, topic="database_migration")
    client = _client_with_repo(repo)

    response = client.get("/cases", params={"topic": "database_migration"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["topic"] == "database_migration"


def test_list_cases_rejects_invalid_priority_with_400() -> None:
    repo = FakeCaseRepository()
    client = _client_with_repo(repo)

    response = client.get("/cases", params={"priority": "urgent"})

    assert response.status_code == 400
    assert "priority" in response.json()["detail"].lower()


def test_list_cases_rejects_invalid_status_with_400() -> None:
    repo = FakeCaseRepository()
    client = _client_with_repo(repo)

    response = client.get("/cases", params={"status": "not-a-real-status"})

    assert response.status_code == 400


def test_list_cases_rejects_out_of_range_limit_with_400() -> None:
    repo = FakeCaseRepository()
    client = _client_with_repo(repo)

    response = client.get("/cases", params={"limit": 0})

    assert response.status_code == 400  # RequestValidationError mapped to 400, not 422


def test_get_case_returns_full_detail() -> None:
    repo = FakeCaseRepository()
    case = _seeded_case(repo)
    client = _client_with_repo(repo)

    response = client.get(f"/cases/{case.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(case.id)
    assert body["topic"] == "payment_system"
    assert body["priority"] == "high"
    assert body["missing_roles"] == ["Security", "Support"]
    assert body["required_roles"] == ["Finance", "Security", "Support"]
    assert len(body["participants"]) == 1
    assert body["participants"][0]["name"] == "Dana Kapoor"
    assert body["channels_used"] == ["email"]
    assert body["attempt_count"] == 1
    assert len(body["timeline"]) == 3  # 1 message + 2 decisions


def test_get_case_404_for_unknown_id() -> None:
    repo = FakeCaseRepository()
    client = _client_with_repo(repo)

    response = client.get(f"/cases/{uuid4()}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_case_timeline_is_chronological_and_typed() -> None:
    repo = FakeCaseRepository()
    case = _seeded_case(repo)
    client = _client_with_repo(repo)

    response = client.get(f"/cases/{case.id}/timeline")

    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 3
    timestamps = [e["timestamp"] for e in entries]
    assert timestamps == sorted(timestamps)
    assert entries[0]["event_type"] == "message"
    assert entries[0]["channel"] == "email"
    assert entries[0]["direction"] == "inbound"
    assert entries[1]["event_type"] == "decision"
    assert entries[1]["node_name"] == "classify_topic"


def test_get_case_timeline_404_for_unknown_id() -> None:
    repo = FakeCaseRepository()
    client = _client_with_repo(repo)

    response = client.get(f"/cases/{uuid4()}/timeline")

    assert response.status_code == 404


def test_get_case_decisions_returns_full_audit_trail() -> None:
    repo = FakeCaseRepository()
    case = _seeded_case(repo)
    client = _client_with_repo(repo)

    response = client.get(f"/cases/{case.id}/decisions")

    assert response.status_code == 200
    decisions = response.json()
    assert len(decisions) == 2
    by_node = {d["node_name"]: d for d in decisions}
    assert by_node["classify_topic"]["status"] == "success"
    assert by_node["classify_topic"]["executed"] is True
    assert by_node["classify_topic"]["confidence"] == 0.95
    assert by_node["create_decision"]["status"] == "pending"
    assert by_node["create_decision"]["executed"] is False
    assert by_node["create_decision"]["chosen_action"]["recipient_name"] == "John Ortiz"


def test_get_case_decisions_404_for_unknown_id() -> None:
    repo = FakeCaseRepository()
    client = _client_with_repo(repo)

    response = client.get(f"/cases/{uuid4()}/decisions")

    assert response.status_code == 404


def test_get_unexpected_error_returns_500_without_a_stack_trace() -> None:
    class _ExplodingRepository(FakeCaseRepository):
        def get_by_id(self, case_id):  # type: ignore[override]
            raise RuntimeError("simulated internal failure with a secret token abc123")

    repo = _ExplodingRepository()
    app = create_app()
    app.dependency_overrides[get_case_repository] = lambda: repo
    # raise_server_exceptions=False: this test deliberately triggers an unhandled exception to
    # verify the 500 handler's *response* — TestClient's default of re-raising it in the test
    # process (so real bugs are loud elsewhere) would defeat the point of this one.
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(f"/cases/{uuid4()}")

    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": "Internal server error"}
    assert "secret token" not in response.text
    assert "abc123" not in response.text
