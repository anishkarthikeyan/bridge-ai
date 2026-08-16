"""Conversation entity — one channel-specific thread under a Case. Splitting this out from
Case (rather than letting Case ≈ one thread) is what lets a case hold an email thread and a
later Telegram thread side by side once the reasoning engine escalates across channels.
Framework-independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.entities.message import Message
from app.domain.value_objects.channel import Channel


@dataclass
class Conversation:
    id: UUID
    case_id: UUID
    channel: Channel
    external_thread_ref: str | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    messages: list[Message] = field(default_factory=list)
