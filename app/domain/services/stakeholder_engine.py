"""StakeholderEngine — compares who's actually in a case's conversation against who a topic
requires, and reports the gap.

Its `communication_health` output is a narrow, stakeholder-gap-only signal (see the banding
rule below) — not the full 0-100 score. It can't be the full score: its input is only
participants and required roles, with no visibility into follow-up timing or conversation
activity. The full picture is CommunicationHealthCalculator's job (next module), which
takes a missing-roles count as just one of several inputs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.value_objects.communication_health import CommunicationHealth


@dataclass(frozen=True)
class StakeholderEvaluation:
    missing_roles: tuple[str, ...]
    present_roles: tuple[str, ...]
    communication_health: CommunicationHealth


class StakeholderEngine:
    def evaluate(
        self, participant_roles: Iterable[str | None], required_roles: Iterable[str]
    ) -> StakeholderEvaluation:
        present = {r for r in participant_roles if r}
        required = list(dict.fromkeys(required_roles))  # de-dup, preserve policy pack order

        present_roles = tuple(r for r in required if r in present)
        missing_roles = tuple(r for r in required if r not in present)

        return StakeholderEvaluation(
            missing_roles=missing_roles,
            present_roles=present_roles,
            communication_health=self._health_from_gap(len(missing_roles), len(required)),
        )

    @staticmethod
    def _health_from_gap(missing_count: int, required_count: int) -> CommunicationHealth:
        """Bands the missing/required ratio into the four-state health enum:
        nothing missing -> HEALTHY, under half missing -> AT_RISK, at least half but not all
        -> STALLED, everything required is missing -> CRITICAL. A case with no required
        roles at all (required_count == 0) has nothing to be at risk of, so it's HEALTHY by
        this signal alone — see the customer_escalation example, where a topic outside the
        policy pack still ends up CRITICAL, but from CommunicationHealthCalculator's other
        inputs, not this one.
        """
        if required_count == 0 or missing_count == 0:
            return CommunicationHealth.HEALTHY
        if missing_count >= required_count:
            return CommunicationHealth.CRITICAL

        ratio = missing_count / required_count
        if ratio < 0.5:
            return CommunicationHealth.AT_RISK
        return CommunicationHealth.STALLED
