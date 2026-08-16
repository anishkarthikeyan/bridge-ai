"""PolicyPack value objects — the immutable, in-memory shape a policy pack (policies/*.yaml)
is loaded into by PolicyLoader (app/domain/services/policy_loader.py).

Deliberately separate from app/application/dto/policy_pack_dto.py: that DTO validates a pack
for *persistence* into the `policies` table (Phase 2's required_roles-only audit mirror).
These value objects are the runtime read path the deterministic reasoning layer actually
uses, and carry the richer per-topic rules (priority, escalation, communication) that
persistence doesn't need. Frozen + tuples throughout — "return immutable policy objects" is
a Phase 3 requirement, not a style preference: nothing downstream may mutate a loaded pack.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects.priority import Priority


@dataclass(frozen=True)
class EscalationRules:
    escalate_after_attempts: int
    escalate_to_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommunicationRules:
    cooldown_hours: int
    max_attempts: int
    escalation_delay_hours: int


@dataclass(frozen=True)
class PolicyTopic:
    topic: str
    required_roles: tuple[str, ...]
    priority: Priority
    escalation_rules: EscalationRules
    communication_rules: CommunicationRules


@dataclass(frozen=True)
class PolicyPack:
    industry_pack: str
    version: str
    topics: tuple[PolicyTopic, ...]

    def get_topic(self, topic: str) -> PolicyTopic | None:
        return next((t for t in self.topics if t.topic == topic), None)
