"""Case entity — the aggregate root and the persisted Conversation Graph for one detected
issue: topic, participants, channels used, required/missing stakeholder roles, communication
health, a chronological timeline, and resolution status.

`participants`, `conversations` (each nesting its `messages`), and `decisions` are real
relationships because each has its own table (see models.py). `required_roles`,
`missing_roles`, `channels_used`, and `timeline` are plain snapshot fields because no table
was requested for them — see the Phase 2 architectural observations for why duplicating
Participant into a second JSON list would be a mistake but these are fine as-is.

`attempt_count` and `next_check_at` (Phase 3) are what let autonomous follow-up survive a
process restart or a reply that arrives days later — the reasoning layer's FollowUpPolicy
(app/domain/services/followup_policy.py) reads and advances them; nothing schedules from
this file. `priority` (Phase 3) is the PriorityEngine's output, persisted so the dashboard
can sort/filter on it without recomputing.

This is a plain dataclass, not an ORM model —
app/integrations/persistence/sqlalchemy/models.py maps to and from it. Nothing in this file,
or anything it imports, knows SQLAlchemy exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.entities.conversation import Conversation
from app.domain.entities.decision import Decision
from app.domain.entities.participant import Participant
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.communication_health import CommunicationHealth
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_state import ResolutionState


@dataclass
class Case:
    id: UUID
    topic: str | None = None

    required_roles: list[str] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)
    channels_used: list[Channel] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    communication_health: CommunicationHealth = CommunicationHealth.HEALTHY
    resolution_status: ResolutionState = ResolutionState.OPEN
    priority: Priority = Priority.MEDIUM

    attempt_count: int = 0
    next_check_at: datetime | None = None

    participants: list[Participant] = field(default_factory=list)
    conversations: list[Conversation] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    created_at: datetime | None = None
    updated_at: datetime | None = None
