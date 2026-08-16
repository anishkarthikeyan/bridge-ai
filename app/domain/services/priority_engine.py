"""PriorityEngine — deterministic priority calculation from topic, missing roles,
communication health, and the policy pack's escalation rules.

Priority only ever escalates upward from the topic's policy-pack baseline — it never lowers
a topic's declared priority. That makes the result explainable as "at least as urgent as the
topic says, and more urgent if these specific deteriorating signals say so" rather than an
opaque blend, and it means a HIGH-priority topic can never be silently downgraded by a
single healthy signal.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects.priority import Priority

_RANK: dict[Priority, int] = {Priority.LOW: 0, Priority.MEDIUM: 1, Priority.HIGH: 2}
_RANK_TO_PRIORITY = {rank: priority for priority, rank in _RANK.items()}

# Escalation thresholds — deliberately named constants, not inline magic numbers, so tuning
# them is a one-line change with an obvious meaning.
_HEALTH_SCORE_FORCES_HIGH = 20
_HEALTH_SCORE_FORCES_MEDIUM = 50
_MISSING_ROLE_RATIO_FORCES_MEDIUM = 0.5


@dataclass(frozen=True)
class PriorityInput:
    base_priority: Priority
    required_roles_count: int
    missing_roles_count: int
    communication_health_score: int
    escalation_threshold_reached: bool
    """True once attempt_count has reached the topic's
    escalation_rules.escalate_after_attempts (computed by the caller, using the same
    PolicyTopic the base_priority came from)."""


class PriorityEngine:
    def calculate(self, data: PriorityInput) -> Priority:
        rank = _RANK[data.base_priority]

        if data.communication_health_score < _HEALTH_SCORE_FORCES_HIGH:
            rank = max(rank, _RANK[Priority.HIGH])
        elif data.communication_health_score < _HEALTH_SCORE_FORCES_MEDIUM:
            rank = max(rank, _RANK[Priority.MEDIUM])

        if data.required_roles_count > 0:
            missing_ratio = data.missing_roles_count / data.required_roles_count
            if missing_ratio >= _MISSING_ROLE_RATIO_FORCES_MEDIUM:
                rank = max(rank, _RANK[Priority.MEDIUM])

        if data.escalation_threshold_reached:
            rank = max(rank, _RANK[Priority.HIGH])

        return _RANK_TO_PRIORITY[rank]
