"""PolicyLoader — reads a YAML policy pack (policies/*.yaml), validates its schema, and
returns an immutable PolicyPack. This is the one file in app/domain/ allowed to touch a
filesystem and a third-party parser (pyyaml): reading a local policy file is the direct,
unavoidable consequence of "policies must not be hardcoded inside Python" (Phase 2) — the
alternative is hand-rolling a YAML parser, which nobody wants. Everything downstream
(TopicResolver, PriorityEngine, ...) consumes only the frozen value objects this returns and
never touches YAML or the filesystem itself.

Distinct from app/application/dto/policy_pack_dto.py: that DTO validates a pack for
*persistence* into the `policies` table (Phase 2's required_roles-only audit mirror). This
loader is the runtime read path deterministic reasoning actually uses, and produces richer,
frozen domain objects (priority, escalation rules, communication rules included).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.domain.exceptions import PolicyValidationError
from app.domain.value_objects.policy_pack import (
    CommunicationRules,
    EscalationRules,
    PolicyPack,
    PolicyTopic,
)
from app.domain.value_objects.priority import Priority

_REQUIRED_TOPIC_KEYS = {
    "topic",
    "required_roles",
    "priority",
    "escalation_rules",
    "communication_rules",
}


class PolicyLoader:
    """Stateless — safe to construct once and reuse, or construct per call."""

    def load(self, path: str | Path) -> PolicyPack:
        raw = self._read_yaml(Path(path))
        return self._parse_pack(raw, source=str(path))

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError as exc:
            raise PolicyValidationError(f"Policy pack not found: {path}") from exc
        except yaml.YAMLError as exc:
            raise PolicyValidationError(f"Policy pack is not valid YAML: {path} ({exc})") from exc

        if not isinstance(data, dict):
            raise PolicyValidationError(f"Policy pack must be a mapping at the top level: {path}")
        return data

    def _parse_pack(self, raw: dict[str, Any], source: str) -> PolicyPack:
        industry_pack = raw.get("industry_pack")
        version = raw.get("version")
        topics_raw = raw.get("topics")

        if not isinstance(industry_pack, str) or not industry_pack:
            raise PolicyValidationError(
                f"{source}: 'industry_pack' is required and must be a non-empty string"
            )
        if not isinstance(version, str) or not version:
            raise PolicyValidationError(f"{source}: 'version' is required and must be a string")
        if not isinstance(topics_raw, list) or not topics_raw:
            raise PolicyValidationError(
                f"{source}: 'topics' is required and must be a non-empty list"
            )

        topics = tuple(self._parse_topic(t, source) for t in topics_raw)

        seen = {t.topic for t in topics}
        if len(seen) != len(topics):
            raise PolicyValidationError(f"{source}: duplicate topic entries are not allowed")

        return PolicyPack(industry_pack=industry_pack, version=version, topics=topics)

    def _parse_topic(self, raw: Any, source: str) -> PolicyTopic:
        if not isinstance(raw, dict):
            raise PolicyValidationError(f"{source}: each topic entry must be a mapping")

        missing_keys = _REQUIRED_TOPIC_KEYS - raw.keys()
        if missing_keys:
            raise PolicyValidationError(
                f"{source}: topic entry missing required keys: {sorted(missing_keys)}"
            )

        topic = raw["topic"]
        if not isinstance(topic, str) or not topic:
            raise PolicyValidationError(f"{source}: 'topic' must be a non-empty string")

        required_roles = raw["required_roles"]
        if (
            not isinstance(required_roles, list)
            or not required_roles
            or not all(isinstance(r, str) and r for r in required_roles)
        ):
            raise PolicyValidationError(
                f"{source}: '{topic}'.required_roles must be a non-empty list of strings"
            )

        try:
            priority = Priority(str(raw["priority"]).lower())
        except ValueError as exc:
            raise PolicyValidationError(
                f"{source}: '{topic}'.priority must be one of {[p.value for p in Priority]}"
            ) from exc

        return PolicyTopic(
            topic=topic,
            required_roles=tuple(required_roles),
            priority=priority,
            escalation_rules=self._parse_escalation_rules(raw["escalation_rules"], topic, source),
            communication_rules=self._parse_communication_rules(
                raw["communication_rules"], topic, source
            ),
        )

    @staticmethod
    def _parse_escalation_rules(raw: Any, topic: str, source: str) -> EscalationRules:
        if not isinstance(raw, dict):
            raise PolicyValidationError(f"{source}: '{topic}'.escalation_rules must be a mapping")
        try:
            escalate_after_attempts = int(raw["escalate_after_attempts"])
            escalate_to_roles = tuple(raw.get("escalate_to_roles", ()))
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyValidationError(
                f"{source}: '{topic}'.escalation_rules is malformed: {exc}"
            ) from exc

        if escalate_after_attempts < 1:
            raise PolicyValidationError(
                f"{source}: '{topic}'.escalation_rules.escalate_after_attempts must be >= 1"
            )

        return EscalationRules(
            escalate_after_attempts=escalate_after_attempts,
            escalate_to_roles=escalate_to_roles,
        )

    @staticmethod
    def _parse_communication_rules(raw: Any, topic: str, source: str) -> CommunicationRules:
        if not isinstance(raw, dict):
            raise PolicyValidationError(
                f"{source}: '{topic}'.communication_rules must be a mapping"
            )
        try:
            cooldown_hours = int(raw["cooldown_hours"])
            max_attempts = int(raw["max_attempts"])
            escalation_delay_hours = int(raw["escalation_delay_hours"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyValidationError(
                f"{source}: '{topic}'.communication_rules is malformed: {exc}"
            ) from exc

        if cooldown_hours < 0 or max_attempts < 1 or escalation_delay_hours < 0:
            raise PolicyValidationError(
                f"{source}: '{topic}'.communication_rules values must be non-negative "
                "(max_attempts must be >= 1)"
            )

        return CommunicationRules(
            cooldown_hours=cooldown_hours,
            max_attempts=max_attempts,
            escalation_delay_hours=escalation_delay_hours,
        )
