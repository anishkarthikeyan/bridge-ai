"""Message entity — one inbound or outbound message on a Conversation; the raw per-thread
audit log. Framework-independent; see
app/integrations/persistence/sqlalchemy/models.py for the ORM mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.value_objects.message_direction import MessageDirection


@dataclass
class Message:
    id: UUID
    conversation_id: UUID
    direction: MessageDirection
    content: str
    sender_participant_id: UUID | None = None
    external_message_ref: str | None = None
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
