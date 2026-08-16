"""FollowUpPolicy — deterministic follow-up timing and attempt-limit logic.

Computes whether a follow-up is due and what should happen next; it does not schedule or
execute anything. There is no timer, no APScheduler call, no I/O here — the (still-stub)
infrastructure/scheduler.py is what will eventually call this on an interval and act on its
output. This is only the policy the scheduler will consult.

Reuses PolicyTopic.communication_rules (cooldown_hours, max_attempts, escalation_delay_hours)
rather than three loose parameters, since those three values already travel together as one
unit from TopicResolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.value_objects.policy_pack import CommunicationRules


@dataclass(frozen=True)
class FollowUpDecision:
    is_due: bool
    """Whether a follow-up should be sent right now."""

    should_escalate: bool
    """Whether this follow-up (or the case generally) should escalate rather than repeat
    the same kind of attempt — either because max_attempts is reached, or because a due
    follow-up has sat unactioned past escalation_delay_hours."""

    next_check_at: datetime | None
    """When to check again. None only when max_attempts has been reached and there is
    nothing left to schedule."""


class FollowUpPolicy:
    def evaluate(
        self,
        *,
        attempt_count: int,
        next_check_at: datetime | None,
        now: datetime,
        rules: CommunicationRules,
    ) -> FollowUpDecision:
        if attempt_count >= rules.max_attempts:
            return FollowUpDecision(is_due=False, should_escalate=True, next_check_at=None)

        # Never contacted yet (no next_check_at set) counts as due immediately.
        is_due = next_check_at is None or now >= next_check_at

        overdue_hours = 0.0
        if next_check_at is not None and now > next_check_at:
            overdue_hours = (now - next_check_at).total_seconds() / 3600
        should_escalate = is_due and overdue_hours >= rules.escalation_delay_hours

        return FollowUpDecision(
            is_due=is_due,
            should_escalate=should_escalate,
            next_check_at=self.compute_next_check_at(now, rules) if is_due else next_check_at,
        )

    @staticmethod
    def compute_next_check_at(sent_at: datetime, rules: CommunicationRules) -> datetime:
        """After a follow-up is actually sent, call this to get the next check-in time.
        Pure arithmetic — the caller (a future use case) is responsible for persisting it."""
        return sent_at + timedelta(hours=rules.cooldown_hours)
