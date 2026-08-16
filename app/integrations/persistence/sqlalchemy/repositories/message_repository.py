"""SQLAlchemy implementation of MessageRepositoryPort."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ports.message_repository_port import MessageRepositoryPort
from app.domain.entities.message import Message as MessageEntity
from app.domain.value_objects.message_direction import MessageDirection
from app.integrations.persistence.sqlalchemy import models


class SqlAlchemyMessageRepository(MessageRepositoryPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, message: MessageEntity) -> MessageEntity:
        row = models.Message(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_participant_id=message.sender_participant_id,
            direction=message.direction.value,
            content=message.content,
            external_message_ref=message.external_message_ref,
        )
        self._session.add(row)
        self._session.flush()
        return _to_entity(row)

    def list_for_conversation(self, conversation_id: UUID) -> list[MessageEntity]:
        stmt = (
            select(models.Message)
            .where(models.Message.conversation_id == conversation_id)
            .order_by(models.Message.sent_at)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_to_entity(row) for row in rows]


def _as_utc(value: datetime | None) -> datetime | None:
    """Same fix as case_repository.py's `_as_utc` — Postgres' TIMESTAMP columns are
    timezone-naive, so a value read back needs its UTC label restored before anything
    compares it against `datetime.now(UTC)`. See that module for the full rationale."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _to_entity(row: models.Message) -> MessageEntity:
    return MessageEntity(
        id=row.id,
        conversation_id=row.conversation_id,
        direction=MessageDirection(row.direction),
        content=row.content,
        sender_participant_id=row.sender_participant_id,
        external_message_ref=row.external_message_ref,
        sent_at=_as_utc(row.sent_at),
        delivered_at=_as_utc(row.delivered_at),
        read_at=_as_utc(row.read_at),
    )
