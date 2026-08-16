"""TopicResolver — looks up a topic's policy definition (required roles, priority,
escalation rules, communication rules) from an already-loaded PolicyPack.

Pure lookup, nothing else: it does not classify free text into a topic (that's
classify_topic, an LLM node — out of scope for the deterministic reasoning layer) and it
does not load YAML itself (that's PolicyLoader). One dependency, injected once.
"""

from __future__ import annotations

from app.domain.exceptions import UnknownTopicError
from app.domain.value_objects.policy_pack import PolicyPack, PolicyTopic


class TopicResolver:
    def __init__(self, policy_pack: PolicyPack) -> None:
        self._policy_pack = policy_pack

    def resolve(self, topic: str) -> PolicyTopic:
        """Raises UnknownTopicError if the topic has no entry in the pack."""
        resolved = self._policy_pack.get_topic(topic)
        if resolved is None:
            raise UnknownTopicError(
                f"No policy entry for topic '{topic}' in pack "
                f"'{self._policy_pack.industry_pack}' v{self._policy_pack.version}"
            )
        return resolved

    def resolve_or_none(self, topic: str) -> PolicyTopic | None:
        """For topics outside the pack (e.g. the customer_escalation demo scenario) — callers
        that should degrade gracefully rather than fail use this instead of resolve().
        """
        return self._policy_pack.get_topic(topic)
