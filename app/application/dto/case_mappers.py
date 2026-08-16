"""Pure domain-entity -> read-DTO mappers for the case/dashboard APIs (Phase 6.5 Parts 11/12).
No I/O and no business rules here — every input is already a fully-hydrated domain entity
(app/domain/entities/), handed in by a router after a repository call. Kept separate from the
routers themselves so the same mapping logic isn't duplicated between GET /cases/{id} and GET
/dashboard/summary's `recent_decisions`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.application.dto.case_snapshot_dto import (
    CaseListItemDTO,
    CaseSnapshotDTO,
    DashboardSummaryDTO,
    DecisionDTO,
    ParticipantSnapshotDTO,
    RecentDecisionDTO,
    TimelineEntryDTO,
)
from app.domain.entities.case import Case
from app.domain.entities.decision import Decision
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_state import ResolutionState

_CLOSED_STATES = {ResolutionState.RESOLVED, ResolutionState.ABANDONED}


def to_case_list_item(case: Case) -> CaseListItemDTO:
    return CaseListItemDTO(
        id=case.id,
        topic=case.topic,
        priority=case.priority.value,
        resolution_status=case.resolution_status.value,
        communication_health=case.communication_health.value,
        missing_roles=list(case.missing_roles),
        attempt_count=case.attempt_count,
        next_check_at=case.next_check_at,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def to_case_snapshot(case: Case) -> CaseSnapshotDTO:
    return CaseSnapshotDTO(
        id=case.id,
        topic=case.topic,
        priority=case.priority.value,
        resolution_status=case.resolution_status.value,
        communication_health=case.communication_health.value,
        required_roles=list(case.required_roles),
        missing_roles=list(case.missing_roles),
        participants=[
            ParticipantSnapshotDTO(
                id=p.id,
                name=p.name,
                role=p.role,
                email=p.email,
                telegram_handle=p.telegram_handle,
                source=p.source.value,
            )
            for p in case.participants
        ],
        channels_used=[c.value for c in case.channels_used],
        attempt_count=case.attempt_count,
        next_check_at=case.next_check_at,
        timeline=build_timeline(case),
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def to_decision_dto(decision: Decision) -> DecisionDTO:
    return DecisionDTO(
        id=decision.id,
        node_name=decision.node_name,
        status=decision.status.value,
        reasoning_summary=decision.reasoning_summary,
        chosen_action=dict(decision.chosen_action),
        confidence=decision.confidence,
        executed=decision.status != DecisionStatus.PENDING,
        created_at=decision.created_at,
    )


def build_timeline(case: Case) -> list[TimelineEntryDTO]:
    """Chronological merge of every message across every conversation plus every decision —
    already-persisted data (Message + Decision rows), not a second store (Part 11)."""
    entries: list[TimelineEntryDTO] = []

    for conversation in case.conversations:
        for message in conversation.messages:
            entries.append(
                TimelineEntryDTO(
                    event_type="message",
                    timestamp=message.sent_at,
                    summary=message.content,
                    channel=conversation.channel.value,
                    direction=message.direction.value,
                )
            )

    for decision in case.decisions:
        entries.append(
            TimelineEntryDTO(
                event_type="decision",
                timestamp=decision.created_at,
                summary=decision.reasoning_summary,
                node_name=decision.node_name,
                status=decision.status.value,
            )
        )

    # Every real timestamp here is UTC-aware (repository reads restore tzinfo — see
    # SqlAlchemyCaseRepository._as_utc); the fallback for a missing one must be too, or
    # sorting a mix of the two raises TypeError.
    entries.sort(key=lambda e: e.timestamp or datetime.min.replace(tzinfo=UTC))
    return entries


def build_dashboard_summary(
    cases: list[Case], now: datetime, recent_decisions_limit: int = 10
) -> DashboardSummaryDTO:
    """Aggregates over an already-fetched case list — Part 12: "Use existing
    repositories/services... Do not create a second database aggregation system." `cases` is
    expected to be every case (the router fetches with no filter/limit), so these counts are
    exact, not sampled."""
    open_cases = [c for c in cases if c.resolution_status not in _CLOSED_STATES]

    all_decisions: list[tuple[Case, Decision]] = [(c, d) for c in cases for d in c.decisions]
    all_decisions.sort(key=lambda pair: pair[1].created_at or datetime.min, reverse=True)

    return DashboardSummaryDTO(
        total_open_cases=len(open_cases),
        total_resolved_cases=sum(
            1 for c in cases if c.resolution_status == ResolutionState.RESOLVED
        ),
        critical_cases=sum(1 for c in open_cases if c.communication_health.value == "critical"),
        high_priority_cases=sum(1 for c in open_cases if c.priority == Priority.HIGH),
        medium_priority_cases=sum(1 for c in open_cases if c.priority == Priority.MEDIUM),
        low_priority_cases=sum(1 for c in open_cases if c.priority == Priority.LOW),
        cases_waiting_for_reply=sum(1 for c in open_cases if c.next_check_at is not None),
        cases_due_for_followup=sum(
            1 for c in open_cases if c.next_check_at is not None and c.next_check_at <= now
        ),
        cases_escalated=sum(
            1 for c in open_cases if any(d.node_name == "escalate" for d in c.decisions)
        ),
        recent_decisions=[
            RecentDecisionDTO(case_id=c.id, **to_decision_dto(d).model_dump())
            for c, d in all_decisions[:recent_decisions_limit]
        ],
    )
