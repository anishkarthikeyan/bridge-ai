"""ResolutionEvaluator — the ONLY decision point after every reply is fully reprocessed
(architecture doc, Phase 6 Change 1). Replaces the Phase 4/5 unconditional loop
(`resume_case -> receive_message` forever) with a real termination condition.

Completely deterministic — it MUST NEVER call the LLM, and does not: every field on
ResolutionEvaluationInput is either a structural fact (missing_roles, communication_health,
attempt_count, timing) or an already-computed deterministic/policy value. Critically, it does
NOT read `classify_topic` or `extract_intent`'s LLM output to judge whether a reply "sounds
like" a confirmation — the LLM boundary explicitly forbids the model from deciding
completion, so resolution is judged purely by structural signals that already exist because
the model classified something (a topic) and deterministic code then required something (a
role): once nobody required is missing and health hasn't collapsed, the structural condition
the whole case exists to satisfy has been satisfied. No sentiment analysis of "did they say
yes" is needed or wanted here.

Field-to-input mapping, since the six inputs named in the architecture doc aren't all
separate fields here:
  - Missing Roles          -> missing_roles
  - Communication Health   -> communication_health
  - Decision Status        -> last_decision_status (the most recent dispatch's outcome)
  - Attempt Count          -> attempt_count
  - Reply History          -> attempt_count doubles for this: every attempt corresponds to
                              one round of outreach, so "how many times have we tried" *is*
                              this case's contact history in deterministic terms — there is
                              no separate reply-content signal ResolutionEvaluator reads.
  - Policy Rules           -> max_attempts, escalate_after_attempts (from the topic's
                              PolicyTopic, or the same defaults DispatchMessageUseCase falls
                              back to when a topic has no policy pack entry)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects.communication_health import CommunicationHealth
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.resolution_outcome import ResolutionOutcome


@dataclass(frozen=True)
class ResolutionEvaluationInput:
    missing_roles: tuple[str, ...]
    communication_health: CommunicationHealth
    last_decision_status: DecisionStatus | None
    attempt_count: int
    now: datetime
    next_check_at: datetime | None
    max_attempts: int
    escalate_after_attempts: int


class ResolutionEvaluator:
    def evaluate(self, data: ResolutionEvaluationInput) -> ResolutionOutcome:
        if self._is_resolved(data):
            return ResolutionOutcome.RESOLVED
        if self._requires_escalation(data):
            return ResolutionOutcome.ESCALATE
        if self._should_follow_up(data):
            return ResolutionOutcome.FOLLOW_UP
        return ResolutionOutcome.WAIT

    @staticmethod
    def _is_resolved(data: ResolutionEvaluationInput) -> bool:
        """No missing stakeholders + policy satisfied (the same fact — required_roles minus
        missing_roles is who showed up) + communication not critical + at least one attempt
        actually made. That last guard matters: a topic with no policy entry has
        missing_roles == () from the start, so without requiring attempt_count > 0 a case
        could "resolve" before ever being contacted.

        Deliberately not `== HEALTHY` but merely `!= CRITICAL`: the expired-follow-up penalty
        in CommunicationHealthCalculator is scored against the *pre-reply* next_check_at, so
        a reply that arrives after cooldown but genuinely closes the gap can still land in
        AT_RISK/STALLED purely from stale timing, not from anything still being wrong.
        """
        return (
            data.attempt_count > 0
            and not data.missing_roles
            and data.communication_health != CommunicationHealth.CRITICAL
        )

    @staticmethod
    def _requires_escalation(data: ResolutionEvaluationInput) -> bool:
        return (
            data.attempt_count >= data.escalate_after_attempts
            or data.attempt_count >= data.max_attempts
            or data.communication_health == CommunicationHealth.CRITICAL
        )

    @staticmethod
    def _should_follow_up(data: ResolutionEvaluationInput) -> bool:
        cooldown_expired = data.next_check_at is None or data.now >= data.next_check_at
        failed_last_attempt = data.last_decision_status == DecisionStatus.FAILED
        return (cooldown_expired or failed_last_attempt) and data.attempt_count < data.max_attempts
