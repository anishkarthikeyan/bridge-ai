"""InboundMessage DTO — the canonical shape every channel adapter normalizes an inbound
event into, and what the brain's Receive Message node consumes. Producing one is the
adapters' job (still out of scope — see architecture doc §9, "DO NOT IMPLEMENT: Email
Adapter, Telegram Adapter, Slack Adapter"); the brain only consumes it.

A plain frozen dataclass, unlike the pydantic DTOs elsewhere in this package
(CaseSnapshotDTO, PolicyPackDTO): this one nests inside AgentState
(app/brain/state.py) and round-trips through LangGraph's Postgres checkpointer on every
pause/resume, so it stays a dataclass for the same reason the rest of AgentState is one —
see that module's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.channel import Channel


@dataclass(frozen=True)
class MessageParticipant:
    name: str
    email: str | None = None
    telegram_handle: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class InboundMessage:
    channel: Channel
    sender: MessageParticipant
    body: str
    external_thread_ref: str | None = None
    external_message_ref: str | None = None
    subject: str | None = None
    cc: tuple[MessageParticipant, ...] = ()
    received_at: datetime | None = None
