"""SQLAlchemy ORM models — Case, Conversation, Participant, Decision, Message, Policy.

These are the only objects in the codebase that know SQLAlchemy's mapping API exists. The
domain layer (app/domain/entities/) has its own framework-independent dataclasses with the
same shape; repository implementations translate between the two so nothing above the
persistence layer imports from this module.

Case is the aggregate root and the persisted Conversation Graph (architecture doc §2):
`participants`, `conversations`, and `decisions` cascade with it — deleting a case deletes
its whole graph. `required_roles`, `missing_roles`, `channels_used`, and `timeline` are JSONB
snapshot columns because no dedicated table was requested for them; duplicating Participant
into a JSON list alongside the real relationship would just create two sources of truth.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.infrastructure.db import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    topic: Mapped[str | None] = mapped_column(index=True)

    required_roles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    missing_roles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    channels_used: Mapped[list[str]] = mapped_column(JSONB, default=list)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    communication_health: Mapped[str] = mapped_column(default="healthy", index=True)
    resolution_status: Mapped[str] = mapped_column(default="open", index=True)
    priority: Mapped[str] = mapped_column(default="medium", index=True)

    # Phase 3: what let autonomous follow-up survive a process restart or a delayed reply —
    # FollowUpPolicy (app/domain/services/followup_policy.py) reads and advances these.
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_check_at: Mapped[datetime | None] = mapped_column(index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="Decision.created_at"
    )


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str]
    role: Mapped[str | None] = mapped_column(index=True)
    email: Mapped[str | None]
    telegram_handle: Mapped[str | None]
    source: Mapped[str] = mapped_column(default="explicit")

    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="participants")
    messages: Mapped[list["Message"]] = relationship(back_populates="sender")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )

    channel: Mapped[str] = mapped_column(index=True)
    external_thread_ref: Mapped[str | None] = mapped_column(index=True)

    opened_at: Mapped[datetime] = mapped_column(server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column()

    case: Mapped["Case"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.sent_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sender_participant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="SET NULL")
    )

    direction: Mapped[str] = mapped_column(index=True)
    content: Mapped[str] = mapped_column(Text)
    external_message_ref: Mapped[str | None] = mapped_column(index=True)

    sent_at: Mapped[datetime] = mapped_column(server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column()
    read_at: Mapped[datetime | None] = mapped_column()

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    sender: Mapped["Participant | None"] = relationship(back_populates="messages")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )

    node_name: Mapped[str] = mapped_column(index=True)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reasoning_summary: Mapped[str] = mapped_column(Text)
    chosen_action: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float | None] = mapped_column()
    # Phase 4: replaces the Phase 3 boolean `executed` — a full lifecycle (pending ->
    # executing -> success/failed) supports retries, replay, and accurate dashboard state.
    status: Mapped[str] = mapped_column(default="pending", index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    case: Mapped["Case"] = relationship(back_populates="decisions")


class Policy(Base):
    """One topic's required-roles rule from a versioned policy pack (policies/*.yaml).

    Loaded from YAML, not authored here — this table is the persisted, queryable, and
    auditable mirror of the pack, not the source of truth. No loader exists yet (Phase 3);
    only the shape is defined now.
    """

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    industry_pack: Mapped[str] = mapped_column(index=True)
    topic: Mapped[str] = mapped_column(index=True)
    required_roles: Mapped[list[str]] = mapped_column(JSONB, default=list)

    version: Mapped[str] = mapped_column(default="1")
    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("industry_pack", "topic", "version", name="uq_policy_pack_topic_version"),
    )
