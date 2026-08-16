"""Test doubles for the brain — an in-memory CaseRepositoryPort and a scripted LLMPort.
Proof that "every node must be independently testable" is actually true: no node in
app/brain/nodes/ needs a database or a network call to be exercised, only these fakes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import (
    EntitiesResult,
    IntentResult,
    LLMPort,
    MessageGenerationContext,
    TopicClassification,
)
from app.domain.entities.case import Case
from app.domain.entities.conversation import Conversation
from app.domain.entities.decision import Decision
from app.domain.entities.participant import Participant
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.resolution_state import ResolutionState


class FakeCaseRepository(CaseRepositoryPort):
    """Dict-backed, no I/O. `decisions` is a flat list callers can assert against directly —
    real auditability with none of a database's setup cost.
    """

    def __init__(self) -> None:
        self.cases: dict[UUID, Case] = {}
        self.decisions: list[Decision] = []
        self.participants: list[Participant] = []
        self.conversations: list[Conversation] = []
        self.conversation_refs: dict[tuple[str, str], UUID] = {}
        """(channel, external_thread_ref) -> case_id — populated by tests that need
        find_by_conversation_ref to resolve to a real case, since this fake has no
        Conversation-to-Case join to derive it from automatically."""
        self.claimed_case_ids: set[UUID] = set()
        """Simulates a real repository's row-locking (SKIP LOCKED) for
        `list_due_for_followup` — see that method below."""

    def get_by_id(self, case_id: UUID) -> Case | None:
        return self.cases.get(case_id)

    def find_by_conversation_ref(self, channel: str, external_thread_ref: str) -> Case | None:
        case_id = self.conversation_refs.get((channel, external_thread_ref))
        return self.cases.get(case_id) if case_id else None

    def list_open(self) -> list[Case]:
        return list(self.cases.values())

    def list_cases(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        topic: str | None = None,
        limit: int | None = 20,
        offset: int = 0,
    ) -> tuple[list[Case], int]:
        matches = [
            c
            for c in self.cases.values()
            if (status is None or c.resolution_status.value == status)
            and (priority is None or c.priority.value == priority)
            and (topic is None or c.topic == topic)
        ]
        matches.sort(key=lambda c: c.created_at or datetime.min.replace(tzinfo=None), reverse=True)
        total = len(matches)
        page = matches[offset:] if limit is None else matches[offset : offset + limit]
        return page, total

    def list_due_for_followup(self, now: datetime, limit: int = 50) -> list[Case]:
        """No real row-locking here (there's only ever one in-process caller in a unit test)
        — `claimed_case_ids` lets a test simulate "already claimed by another tick/process"
        without needing a real database, mirroring the real repository's SKIP LOCKED
        contract: a claimed case is excluded exactly like a locked row would be."""
        closed = {ResolutionState.RESOLVED, ResolutionState.ABANDONED}
        due = [
            c
            for c in self.cases.values()
            if c.resolution_status not in closed
            and c.next_check_at is not None
            and c.next_check_at <= now
            and c.id not in self.claimed_case_ids
        ]
        due.sort(key=lambda c: c.next_check_at)
        return due[:limit]

    def add(self, case: Case) -> Case:
        self.cases[case.id] = case
        return case

    def save(self, case: Case) -> Case:
        existing = self.cases.get(case.id)
        if existing is None:
            raise ValueError(f"Case {case.id} does not exist")
        existing.topic = case.topic
        existing.required_roles = list(case.required_roles)
        existing.missing_roles = list(case.missing_roles)
        existing.channels_used = list(case.channels_used)
        existing.timeline = list(case.timeline)
        existing.communication_health = case.communication_health
        existing.resolution_status = case.resolution_status
        existing.priority = case.priority
        existing.attempt_count = case.attempt_count
        existing.next_check_at = case.next_check_at
        return existing

    def add_participant(self, case_id: UUID, participant: Participant) -> Participant:
        self.participants.append(participant)
        case = self.cases.get(case_id)
        if case is not None:
            case.participants.append(participant)
        return participant

    def add_conversation(self, case_id: UUID, conversation: Conversation) -> Conversation:
        self.conversations.append(conversation)
        case = self.cases.get(case_id)
        if case is not None:
            case.conversations.append(conversation)
        if conversation.external_thread_ref is not None:
            # Mirrors the real repository's Case-join-Conversation lookup — receive_message
            # now calls add_conversation for real, so this must "just work" without a test
            # manually pre-populating conversation_refs the way earlier phases did.
            self.conversation_refs[
                (conversation.channel.value, conversation.external_thread_ref)
            ] = case_id
        return conversation

    def add_decision(self, case_id: UUID, decision: Decision) -> Decision:
        self.decisions.append(decision)
        case = self.cases.get(case_id)
        if case is not None:
            # A real Case.decisions relationship (SqlAlchemyCaseRepository) reflects a fresh
            # add immediately too — DispatchNode relies on exactly this to look a just-created
            # Decision back up by id via get_by_id().decisions.
            case.decisions.append(decision)
        return decision

    def update_decision_status(self, decision_id: UUID, status: DecisionStatus) -> Decision:
        for i, decision in enumerate(self.decisions):
            if decision.id == decision_id:
                updated = replace(decision, status=status)
                self.decisions[i] = updated
                for case in self.cases.values():
                    for j, case_decision in enumerate(case.decisions):
                        if case_decision.id == decision_id:
                            case.decisions[j] = updated
                return updated
        raise ValueError(f"Decision {decision_id} does not exist")


class FakeLLMPort(LLMPort):
    """Scripted, deterministic responses — the point is to test the brain's orchestration,
    not an actual model. `topic` is configurable (default "payment_system", unchanged from
    earlier phases) so a test can pick a topic with different policy thresholds — e.g.
    database_migration's escalate_after_attempts=2 vs payment_system's =1 — without needing
    a second fake class."""

    def __init__(self, topic: str = "payment_system") -> None:
        self._topic = topic

    def extract_intent(self, text: str) -> IntentResult:
        return IntentResult(intent="request_review", confidence=0.9)

    def extract_entities(self, text: str) -> EntitiesResult:
        return EntitiesResult(people=("Dana Kapoor",), mentioned_roles=("Security",), dates=())

    def classify_topic(self, text: str) -> TopicClassification:
        return TopicClassification(topic=self._topic, confidence=0.95)

    def generate_message(self, context: MessageGenerationContext) -> str:
        return (
            f"Hi {context.recipient_name}, following up on {context.topic}: "
            f"we still need {', '.join(context.missing_roles) or 'no one else'} looped in."
        )
