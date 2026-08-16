"""Participant entity — a person known to a case's Conversation Graph: who they are, what
role they hold, and which channel identities reach them. Case-scoped (not a global contact
directory) per the Phase 2 model list. Framework-independent; the SQLAlchemy mapping lives
in app/integrations/persistence/sqlalchemy/models.py, and the repository implementation
translates between the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.value_objects.participant_source import ParticipantSource


@dataclass
class Participant:
    id: UUID
    case_id: UUID
    name: str
    role: str | None = None
    email: str | None = None
    telegram_handle: str | None = None
    source: ParticipantSource = ParticipantSource.EXPLICIT
    joined_at: datetime | None = None
