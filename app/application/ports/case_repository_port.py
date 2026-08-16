"""CaseRepositoryPort — abstract persistence interface for the Case aggregate: the Case
itself plus its Participants, Conversations, and Decisions (the Conversation Graph, see
architecture doc §2). Use cases and the brain depend on this interface, never on SQLAlchemy
directly (architecture doc §4, clean architecture).

Conversation and Participant have no repository of their own — they have no lifecycle
independent of their Case, so mutations to them go through the aggregate root, here.
Message does get its own port (message_repository_port.py): it is high-volume, append-only,
and queried by conversation independently of loading a whole case.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from app.domain.entities.case import Case
from app.domain.entities.conversation import Conversation
from app.domain.entities.decision import Decision
from app.domain.entities.participant import Participant
from app.domain.value_objects.decision_status import DecisionStatus


class CaseRepositoryPort(ABC):
    @abstractmethod
    def get_by_id(self, case_id: UUID) -> Case | None: ...

    @abstractmethod
    def find_by_conversation_ref(self, channel: str, external_thread_ref: str) -> Case | None:
        """Look up the case owning a conversation thread, by channel + external thread ref.

        Pure data lookup — what a caller does with the result (open a new case vs. resume
        this one) is a business decision made elsewhere, not here.
        """
        ...

    @abstractmethod
    def list_open(self) -> list[Case]: ...

    @abstractmethod
    def list_cases(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        topic: str | None = None,
        limit: int | None = 20,
        offset: int = 0,
    ) -> tuple[list[Case], int]:
        """Filtered, paginated case listing for the read APIs (Phase 6.5 Part 11) and the
        dashboard aggregation (Part 12) — the one general-purpose query both read against,
        rather than each inventing its own. Returns `(page, total_matching_count)`; `limit=None`
        means "no limit" (the dashboard's use case: fetch every matching case to aggregate
        over). Ordered newest-first by `created_at` — a stable, obvious default for a list
        endpoint with no explicit sort requested.
        """
        ...

    @abstractmethod
    def list_due_for_followup(self, now: datetime, limit: int = 50) -> list[Case]:
        """Cases whose `next_check_at` has arrived and that are still open — what the
        follow-up scheduler (Part 8) wakes up to find. Deliberately separate from `list_open`
        (which has no timing filter and returns everything): the scheduler must never re-walk
        every open case on every tick, only the ones actually due.

        Implementations that back a real database MUST make concurrent calls from multiple
        scheduler processes/ticks safe against dispatching the same case twice — e.g. via
        `SELECT ... FOR UPDATE SKIP LOCKED` — since this is the scheduler's only query and the
        one place duplicate-dispatch prevention has to hold (Part 8, "Scheduler Safety"). A
        case returned here is *not yet claimed*; the caller is expected to persist its own
        change (a new decision + advanced next_check_at, via the normal Decision lifecycle)
        before the transaction that produced this list commits, so a concurrent scan skips it.
        """
        ...

    @abstractmethod
    def add(self, case: Case) -> Case: ...

    @abstractmethod
    def save(self, case: Case) -> Case:
        """Persists changes to the Case's own scalar/JSON fields (topic, required_roles,
        missing_roles, channels_used, timeline, communication_health, resolution_status).
        Does not touch participants/conversations/decisions — use the add_* methods below
        for those, so partial graph updates never require reloading and rewriting the whole
        aggregate.
        """
        ...

    @abstractmethod
    def add_participant(self, case_id: UUID, participant: Participant) -> Participant: ...

    @abstractmethod
    def add_conversation(self, case_id: UUID, conversation: Conversation) -> Conversation: ...

    @abstractmethod
    def add_decision(self, case_id: UUID, decision: Decision) -> Decision: ...

    @abstractmethod
    def update_decision_status(self, decision_id: UUID, status: DecisionStatus) -> Decision:
        """Transitions a Decision's status (architecture doc, Change 1: the Decision
        lifecycle PENDING -> EXECUTING -> SUCCESS/FAILED). The one mutation a Decision
        undergoes after creation — everything else about it is immutable history.
        """
        ...
