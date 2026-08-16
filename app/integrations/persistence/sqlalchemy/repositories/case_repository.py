"""SQLAlchemy implementation of CaseRepositoryPort.

Every method translates between the ORM models in models.py and the framework-independent
domain entities in app/domain/entities/ — nothing above this file ever sees a SQLAlchemy
object. get_by_id / find_by_conversation_ref / list_open all eager-load the full aggregate
(participants, conversations + their messages, decisions) with selectinload so hydrating a
Case never triggers per-relationship N+1 queries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.domain.entities.case import Case as CaseEntity
from app.domain.entities.conversation import Conversation as ConversationEntity
from app.domain.entities.decision import Decision as DecisionEntity
from app.domain.entities.message import Message as MessageEntity
from app.domain.entities.participant import Participant as ParticipantEntity
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.communication_health import CommunicationHealth
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.message_direction import MessageDirection
from app.domain.value_objects.participant_source import ParticipantSource
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_state import ResolutionState
from app.integrations.persistence.sqlalchemy import models

_AGGREGATE_OPTIONS = (
    selectinload(models.Case.participants),
    selectinload(models.Case.conversations).selectinload(models.Conversation.messages),
    selectinload(models.Case.decisions),
)


class SqlAlchemyCaseRepository(CaseRepositoryPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, case_id: UUID) -> CaseEntity | None:
        stmt = select(models.Case).where(models.Case.id == case_id).options(*_AGGREGATE_OPTIONS)
        row = self._session.execute(stmt).scalar_one_or_none()
        return _case_to_entity(row) if row is not None else None

    def find_by_conversation_ref(self, channel: str, external_thread_ref: str) -> CaseEntity | None:
        stmt = (
            select(models.Case)
            .join(models.Conversation)
            .where(
                models.Conversation.channel == channel,
                models.Conversation.external_thread_ref == external_thread_ref,
            )
            .options(*_AGGREGATE_OPTIONS)
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return _case_to_entity(row) if row is not None else None

    def list_open(self) -> list[CaseEntity]:
        closed = (ResolutionState.RESOLVED.value, ResolutionState.ABANDONED.value)
        stmt = (
            select(models.Case)
            .where(models.Case.resolution_status.not_in(closed))
            .options(*_AGGREGATE_OPTIONS)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_case_to_entity(row) for row in rows]

    def list_cases(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        topic: str | None = None,
        limit: int | None = 20,
        offset: int = 0,
    ) -> tuple[list[CaseEntity], int]:
        filters = self._list_filters(status=status, priority=priority, topic=topic)

        count_stmt = select(func.count()).select_from(models.Case).where(*filters)
        total = self._session.execute(count_stmt).scalar_one()

        stmt = (
            select(models.Case)
            .where(*filters)
            .options(*_AGGREGATE_OPTIONS)
            .order_by(models.Case.created_at.desc())
            .offset(offset)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self._session.execute(stmt).scalars().all()
        return [_case_to_entity(row) for row in rows], total

    def list_due_for_followup(self, now: datetime, limit: int = 50) -> list[CaseEntity]:
        closed = (ResolutionState.RESOLVED.value, ResolutionState.ABANDONED.value)
        stmt = (
            select(models.Case)
            .where(
                models.Case.resolution_status.not_in(closed),
                models.Case.next_check_at.is_not(None),
                models.Case.next_check_at <= now,
            )
            .options(*_AGGREGATE_OPTIONS)
            .order_by(models.Case.next_check_at.asc())
            .limit(limit)
            # SKIP LOCKED is what makes this safe across concurrent scheduler ticks/processes
            # (Part 8, "Scheduler Safety") — a row another transaction already holds (because
            # it's mid-dispatch for the same case) is silently excluded rather than blocked
            # on, so a concurrent scan gets a disjoint set of cases instead of waiting or
            # double-processing the same one.
            .with_for_update(skip_locked=True)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_case_to_entity(row) for row in rows]

    @staticmethod
    def _list_filters(*, status: str | None, priority: str | None, topic: str | None) -> list[Any]:
        filters: list[Any] = []
        if status is not None:
            filters.append(models.Case.resolution_status == status)
        if priority is not None:
            filters.append(models.Case.priority == priority)
        if topic is not None:
            filters.append(models.Case.topic == topic)
        return filters

    def add(self, case: CaseEntity) -> CaseEntity:
        row = _case_to_model(case)
        self._session.add(row)
        self._session.flush()
        return _case_to_entity(row)

    def save(self, case: CaseEntity) -> CaseEntity:
        row = self._session.get(models.Case, case.id)
        if row is None:
            raise ValueError(f"Case {case.id} does not exist")
        row.topic = case.topic
        row.required_roles = list(case.required_roles)
        row.missing_roles = list(case.missing_roles)
        row.channels_used = [c.value for c in case.channels_used]
        row.timeline = list(case.timeline)
        row.communication_health = case.communication_health.value
        row.resolution_status = case.resolution_status.value
        row.priority = case.priority.value
        row.attempt_count = case.attempt_count
        row.next_check_at = case.next_check_at
        self._session.flush()
        return _case_to_entity(row)

    def add_participant(self, case_id: UUID, participant: ParticipantEntity) -> ParticipantEntity:
        row = models.Participant(
            id=participant.id,
            case_id=case_id,
            name=participant.name,
            role=participant.role,
            email=participant.email,
            telegram_handle=participant.telegram_handle,
            source=participant.source.value,
        )
        self._session.add(row)
        self._session.flush()
        return _participant_to_entity(row)

    def add_conversation(
        self, case_id: UUID, conversation: ConversationEntity
    ) -> ConversationEntity:
        row = models.Conversation(
            id=conversation.id,
            case_id=case_id,
            channel=conversation.channel.value,
            external_thread_ref=conversation.external_thread_ref,
        )
        self._session.add(row)
        self._session.flush()
        return _conversation_to_entity(row)

    def add_decision(self, case_id: UUID, decision: DecisionEntity) -> DecisionEntity:
        row = models.Decision(
            id=decision.id,
            case_id=case_id,
            node_name=decision.node_name,
            input_snapshot=dict(decision.input_snapshot),
            reasoning_summary=decision.reasoning_summary,
            chosen_action=dict(decision.chosen_action),
            confidence=decision.confidence,
            status=decision.status.value,
        )
        self._session.add(row)
        self._session.flush()
        return _decision_to_entity(row)

    def update_decision_status(self, decision_id: UUID, status: DecisionStatus) -> DecisionEntity:
        row = self._session.get(models.Decision, decision_id)
        if row is None:
            raise ValueError(f"Decision {decision_id} does not exist")
        row.status = status.value
        self._session.flush()
        return _decision_to_entity(row)


def _as_utc(value: datetime | None) -> datetime | None:
    """Postgres' TIMESTAMP columns are timezone-naive (see the Phase 2/3 migrations), so
    SQLAlchemy returns a naive datetime on every read. Every domain service compares
    timestamps against `datetime.now(UTC)` (deliberately, for testability — see
    CommunicationHealthCalculator, ResolutionEvaluator), which raises TypeError against a
    naive one. This is where that gets fixed — once, at the ORM/domain boundary, for every
    timestamp this repository hands out — rather than at each of the many call sites that
    compare a timestamp against "now". Safe because every timestamp this app writes already
    came from `datetime.now(UTC)`; a naive value read back is always UTC, just missing the
    label — guaranteed by app/infrastructure/db.py pinning every connection's PostgreSQL
    session to `TIME ZONE 'UTC'` on connect (see that module's docstring for why a naive
    column's stored value otherwise depends on the session timezone, not just its label).
    """
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# --- ORM row -> domain entity -------------------------------------------------------------


def _case_to_entity(row: models.Case) -> CaseEntity:
    return CaseEntity(
        id=row.id,
        topic=row.topic,
        required_roles=list(row.required_roles),
        missing_roles=list(row.missing_roles),
        channels_used=[Channel(c) for c in row.channels_used],
        timeline=list(row.timeline),
        communication_health=CommunicationHealth(row.communication_health),
        resolution_status=ResolutionState(row.resolution_status),
        priority=Priority(row.priority),
        attempt_count=row.attempt_count,
        next_check_at=_as_utc(row.next_check_at),
        participants=[_participant_to_entity(p) for p in row.participants],
        conversations=[_conversation_to_entity(c) for c in row.conversations],
        decisions=[_decision_to_entity(d) for d in row.decisions],
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


def _participant_to_entity(row: models.Participant) -> ParticipantEntity:
    return ParticipantEntity(
        id=row.id,
        case_id=row.case_id,
        name=row.name,
        role=row.role,
        email=row.email,
        telegram_handle=row.telegram_handle,
        source=ParticipantSource(row.source),
        joined_at=_as_utc(row.joined_at),
    )


def _conversation_to_entity(row: models.Conversation) -> ConversationEntity:
    return ConversationEntity(
        id=row.id,
        case_id=row.case_id,
        channel=Channel(row.channel),
        external_thread_ref=row.external_thread_ref,
        opened_at=_as_utc(row.opened_at),
        closed_at=_as_utc(row.closed_at),
        messages=[_message_to_entity(m) for m in row.messages],
    )


def _message_to_entity(row: models.Message) -> MessageEntity:
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


def _decision_to_entity(row: models.Decision) -> DecisionEntity:
    return DecisionEntity(
        id=row.id,
        case_id=row.case_id,
        node_name=row.node_name,
        reasoning_summary=row.reasoning_summary,
        input_snapshot=dict(row.input_snapshot),
        chosen_action=dict(row.chosen_action),
        confidence=row.confidence,
        status=DecisionStatus(row.status),
        created_at=_as_utc(row.created_at),
    )


# --- domain entity -> ORM row (insert-only; save() above handles Case field updates) ------


def _case_to_model(case: CaseEntity) -> models.Case:
    return models.Case(
        id=case.id,
        topic=case.topic,
        required_roles=list(case.required_roles),
        missing_roles=list(case.missing_roles),
        channels_used=[c.value for c in case.channels_used],
        timeline=list(case.timeline),
        communication_health=case.communication_health.value,
        resolution_status=case.resolution_status.value,
        priority=case.priority.value,
        attempt_count=case.attempt_count,
        next_check_at=case.next_check_at,
        participants=[
            models.Participant(
                id=p.id,
                name=p.name,
                role=p.role,
                email=p.email,
                telegram_handle=p.telegram_handle,
                source=p.source.value,
            )
            for p in case.participants
        ],
        conversations=[
            models.Conversation(
                id=c.id,
                channel=c.channel.value,
                external_thread_ref=c.external_thread_ref,
                messages=[
                    models.Message(
                        id=m.id,
                        sender_participant_id=m.sender_participant_id,
                        direction=m.direction.value,
                        content=m.content,
                        external_message_ref=m.external_message_ref,
                    )
                    for m in c.messages
                ],
            )
            for c in case.conversations
        ],
        decisions=[
            models.Decision(
                id=d.id,
                node_name=d.node_name,
                input_snapshot=dict(d.input_snapshot),
                reasoning_summary=d.reasoning_summary,
                chosen_action=dict(d.chosen_action),
                confidence=d.confidence,
                status=d.status.value,
            )
            for d in case.decisions
        ],
    )
