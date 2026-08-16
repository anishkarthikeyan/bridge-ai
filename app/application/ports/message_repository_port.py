"""MessageRepositoryPort — abstract persistence interface for Message, the raw per-
conversation audit log. Separate from CaseRepositoryPort because messages are high-volume,
append-only, and are queried by conversation independently of loading a full case aggregate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.message import Message


class MessageRepositoryPort(ABC):
    @abstractmethod
    def add(self, message: Message) -> Message: ...

    @abstractmethod
    def list_for_conversation(self, conversation_id: UUID) -> list[Message]: ...
