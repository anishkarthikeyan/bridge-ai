"""CommunicationHealthCalculator — deterministic 0-100 scoring for a case's communication
health, and the mapping from that score back to the four-state CommunicationHealth enum
persisted on Case.

Starts at 100 and subtracts for: missing stakeholders, outstanding follow-ups (attempts
already made while still awaiting a reply), expired follow-ups (a due follow-up that hasn't
happened yet), and inactive conversations (no message activity for a while). Every input is
passed in explicitly, including `now` — this class never reads the system clock, so a given
input always produces the same score.

Weights are constructor-injected with sensible defaults, not hardcoded, so tuning them is a
config change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.communication_health import CommunicationHealth


@dataclass(frozen=True)
class CommunicationHealthWeights:
    starting_score: int = 100
    missing_stakeholder_penalty: int = 15
    outstanding_followup_penalty: int = 5
    expired_followup_penalty: int = 20
    inactive_conversation_penalty_per_day: int = 5
    inactive_conversation_grace_hours: int = 24


@dataclass(frozen=True)
class CommunicationHealthInput:
    missing_roles_count: int
    attempt_count: int
    next_check_at: datetime | None
    last_activity_at: datetime | None
    now: datetime


class CommunicationHealthCalculator:
    def __init__(self, weights: CommunicationHealthWeights | None = None) -> None:
        self._weights = weights or CommunicationHealthWeights()

    def score(self, data: CommunicationHealthInput) -> int:
        raw = (
            self._weights.starting_score
            - self._missing_stakeholder_penalty(data)
            - self._outstanding_followup_penalty(data)
            - self._expired_followup_penalty(data)
            - self._inactive_conversation_penalty(data)
        )
        return max(0, min(100, raw))

    def _missing_stakeholder_penalty(self, data: CommunicationHealthInput) -> int:
        return data.missing_roles_count * self._weights.missing_stakeholder_penalty

    def _outstanding_followup_penalty(self, data: CommunicationHealthInput) -> int:
        return data.attempt_count * self._weights.outstanding_followup_penalty

    def _expired_followup_penalty(self, data: CommunicationHealthInput) -> int:
        if data.next_check_at is not None and data.now > data.next_check_at:
            return self._weights.expired_followup_penalty
        return 0

    def _inactive_conversation_penalty(self, data: CommunicationHealthInput) -> int:
        if data.last_activity_at is None:
            return 0
        idle_hours = (data.now - data.last_activity_at).total_seconds() / 3600
        grace = self._weights.inactive_conversation_grace_hours
        if idle_hours <= grace:
            return 0
        idle_days_over_grace = int((idle_hours - grace) // 24) + 1
        return idle_days_over_grace * self._weights.inactive_conversation_penalty_per_day

    @staticmethod
    def to_health_state(score: int) -> CommunicationHealth:
        """Bands a 0-100 score into the persisted CommunicationHealth enum:
        80-100 HEALTHY, 50-79 AT_RISK, 20-49 STALLED, 0-19 CRITICAL.
        """
        if score >= 80:
            return CommunicationHealth.HEALTHY
        if score >= 50:
            return CommunicationHealth.AT_RISK
        if score >= 20:
            return CommunicationHealth.STALLED
        return CommunicationHealth.CRITICAL
