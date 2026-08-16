"""Read-model DTOs for the dashboard-facing APIs (Phase 6.5 Parts 11/12) — the shapes GET
/cases, GET /cases/{id}, GET /cases/{id}/timeline, GET /cases/{id}/decisions, and GET
/dashboard/summary actually return. Repository ports return domain entities
(app/domain/entities/case.py); these pydantic models are for one layer further out, so a
caller of the API never sees a domain dataclass or a SQLAlchemy model directly (Part 11: "Do
not expose SQLAlchemy models directly").

Built once, here, and reused everywhere a case/decision shape needs serializing rather than
each router inventing its own — the "existing DTO" Part 3's "do not invent new schemas"
principle applies just as much to read models as to LLM output shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class ParticipantSnapshotDTO(BaseModel):
    id: UUID
    name: str
    role: str | None = None
    email: str | None = None
    telegram_handle: str | None = None
    source: str


class TimelineEntryDTO(BaseModel):
    """One chronological entry in a case's activity feed — assembled at read time from
    already-persisted Message and Decision rows (Part 11: "Do not invent a second timeline
    store"), never from `Case.timeline` itself, which nothing currently writes to."""

    event_type: Literal["message", "decision"]
    timestamp: datetime | None
    summary: str
    channel: str | None = None
    direction: str | None = None
    node_name: str | None = None
    status: str | None = None


class CaseListItemDTO(BaseModel):
    """One row of GET /cases — deliberately lighter than CaseSnapshotDTO (no participants,
    timeline, etc.): a list endpoint that eager-loads every case's full graph does not scale,
    and a list view doesn't need that detail (Part 11: "Do not overengineer filtering")."""

    id: UUID
    topic: str | None = None
    priority: str
    resolution_status: str
    communication_health: str
    missing_roles: list[str] = []
    attempt_count: int
    next_check_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseListResponseDTO(BaseModel):
    items: list[CaseListItemDTO]
    total: int
    limit: int | None = None
    offset: int = 0


class CaseSnapshotDTO(BaseModel):
    """GET /cases/{id} — everything Part 11's case-detail requirements list, and nothing a
    dashboard wasn't asked to render (no raw decisions/messages here; those have their own,
    fuller endpoints — GET /cases/{id}/decisions and GET /cases/{id}/timeline)."""

    id: UUID
    topic: str | None = None
    priority: str
    resolution_status: str
    communication_health: str
    required_roles: list[str] = []
    missing_roles: list[str] = []
    participants: list[ParticipantSnapshotDTO] = []
    channels_used: list[str] = []
    attempt_count: int
    next_check_at: datetime | None = None
    timeline: list[TimelineEntryDTO] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DecisionDTO(BaseModel):
    """GET /cases/{id}/decisions — the full audit-trail row Part 11 asks for. `executed`
    mirrors the Decision lifecycle (architecture doc Change 1): PENDING has not been acted on
    yet; every other status means dispatch was at least attempted."""

    id: UUID
    node_name: str
    status: str
    reasoning_summary: str
    chosen_action: dict[str, Any] = {}
    confidence: float | None = None
    executed: bool
    created_at: datetime | None = None


class RecentDecisionDTO(DecisionDTO):
    """A DecisionDTO plus which case it belongs to — only meaningful once decisions from
    multiple cases are mixed together, as in the dashboard's `recent_decisions`."""

    case_id: UUID


class DashboardSummaryDTO(BaseModel):
    """GET /dashboard/summary (Part 12) — one call the frontend can render an overview from,
    instead of several separate list/count queries."""

    total_open_cases: int
    total_resolved_cases: int
    critical_cases: int
    high_priority_cases: int
    medium_priority_cases: int
    low_priority_cases: int
    cases_waiting_for_reply: int
    cases_due_for_followup: int
    cases_escalated: int
    recent_decisions: list[RecentDecisionDTO] = []
