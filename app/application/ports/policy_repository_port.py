"""PolicyRepositoryPort — abstract persistence interface for Policy, the DB mirror of a
loaded YAML policy pack (policies/*.yaml). Lookup and storage only — no evaluation. The
deterministic policy engine that reads through this port is Phase 3 (see architecture doc
§3, LLM boundary — required-role lookups must stay deterministic).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.application.dto.policy_pack_dto import PolicyTopicDTO


class PolicyRepositoryPort(ABC):
    @abstractmethod
    def get_active(self, industry_pack: str, topic: str) -> PolicyTopicDTO | None: ...

    @abstractmethod
    def list_active(self, industry_pack: str) -> list[PolicyTopicDTO]: ...

    @abstractmethod
    def replace_pack(self, industry_pack: str, version: str, topics: list[PolicyTopicDTO]) -> None:
        """Deactivates the current active version of a pack and inserts the given topics as
        the new active version. Used by the (not-yet-written) YAML pack loader — no loader
        exists yet, only the storage operation it will call.
        """
        ...
