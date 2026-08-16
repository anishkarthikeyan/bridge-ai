"""RunFollowupSweepUseCase — the scheduler's only entry point into application/domain logic
(Phase 6.5 Part 8). Deliberately tiny and rule-free: "periodically wake up -> find cases that
are due -> invoke the existing application/domain workflow -> allow existing deterministic
reasoning to decide what happens." Every actual decision (follow up, escalate, resolve, or do
nothing) is EvaluateCaseUseCase's job, which is itself just direct calls into the same brain
nodes graph.py wires — this class does not know what FOLLOW_UP or ESCALATE mean.

`app/infrastructure/scheduler.py` is what calls `run()` on an interval; this class has no
timer of its own (Part 8: "The scheduler must contain NO business rules" — and, symmetrically,
this use case contains no scheduling).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.use_cases.evaluate_case import EvaluateCaseUseCase
from app.domain.value_objects.resolution_outcome import ResolutionOutcome

logger = logging.getLogger(__name__)

DEFAULT_BATCH_LIMIT = 50


@dataclass(frozen=True)
class FollowupSweepEntry:
    case_id: UUID
    outcome: ResolutionOutcome | None
    """None only if evaluating this particular case raised — see RunFollowupSweepUseCase.run's
    docstring: one case's failure never aborts the rest of the sweep."""
    error: str | None = None


class RunFollowupSweepUseCase:
    def __init__(
        self,
        case_repository: CaseRepositoryPort,
        evaluate_case_use_case: EvaluateCaseUseCase,
        *,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._case_repository = case_repository
        self._evaluate_case_use_case = evaluate_case_use_case
        self._batch_limit = batch_limit
        self._clock = clock

    def run(self) -> list[FollowupSweepEntry]:
        """Finds every case due for follow-up right now and re-evaluates each one. A single
        case raising (e.g. a Featherless call in generate_message exhausting its retries) is
        recorded and skipped rather than aborting the whole batch — one unreachable case's
        transient failure should not stall follow-up for every other due case in the same
        tick; the case remains due (its next_check_at is unchanged) and is simply picked up
        again on the next tick.
        """
        now = self._clock()
        due_cases = self._case_repository.list_due_for_followup(now, limit=self._batch_limit)

        results: list[FollowupSweepEntry] = []
        for case in due_cases:
            try:
                outcome = self._evaluate_case_use_case.evaluate(case)
            except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring above
                logger.exception("Follow-up sweep failed to evaluate case %s", case.id)
                results.append(FollowupSweepEntry(case_id=case.id, outcome=None, error=str(exc)))
                continue
            results.append(FollowupSweepEntry(case_id=case.id, outcome=outcome))

        if results:
            logger.info(
                "Follow-up sweep processed %d due case(s): %s",
                len(results),
                [
                    (str(r.case_id), r.outcome.value if r.outcome else f"error: {r.error}")
                    for r in results
                ],
            )
        return results
