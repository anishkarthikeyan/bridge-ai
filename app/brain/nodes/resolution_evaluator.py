"""ResolutionEvaluatorNode — the ONLY decision point after every reply is fully reprocessed
(architecture doc, Phase 6 Change 1). Wraps the deterministic ResolutionEvaluator domain
service (app/domain/services/resolution_evaluator.py) — this node's only job is to gather
that service's six inputs from state and hand its one output (a ResolutionOutcome) to the
conditional-edge routing function in graph.py, which is what actually decides where the
graph goes next. This node itself never branches; LangGraph's `add_conditional_edges` does.

Policy defaults (when `state.policy_topic` is None — a topic outside the pack) mirror
DispatchMessageUseCase's fallback (Phase 5): a topic with no policy entry degrades to a
sensible default rather than blocking the whole case.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.services.resolution_evaluator import ResolutionEvaluationInput, ResolutionEvaluator

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_ESCALATE_AFTER_ATTEMPTS = 3


class ResolutionEvaluatorNode(BrainNode):
    node_name = "resolution_evaluator"

    def __init__(
        self,
        case_repository: CaseRepositoryPort,
        evaluator: ResolutionEvaluator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(case_repository)
        self._evaluator = evaluator or ResolutionEvaluator()
        self._clock = clock

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph
        policy_topic = state.policy_topic

        max_attempts = (
            policy_topic.communication_rules.max_attempts if policy_topic else _DEFAULT_MAX_ATTEMPTS
        )
        escalate_after_attempts = (
            policy_topic.escalation_rules.escalate_after_attempts
            if policy_topic
            else _DEFAULT_ESCALATE_AFTER_ATTEMPTS
        )

        data = ResolutionEvaluationInput(
            missing_roles=tuple(graph.missing_roles),
            communication_health=graph.communication_health,
            last_decision_status=state.last_dispatch_status,
            attempt_count=graph.attempt_count,
            now=self._clock(),
            next_check_at=graph.next_check_at,
            max_attempts=max_attempts,
            escalate_after_attempts=escalate_after_attempts,
        )
        outcome = self._evaluator.evaluate(data)

        return NodeResult(
            reasoning_summary=(
                f"Resolution: {outcome.value} — missing_roles={list(data.missing_roles)}, "
                f"health={data.communication_health.value}, "
                f"attempts={data.attempt_count}/{max_attempts} "
                f"(escalate at {escalate_after_attempts}), "
                f"last_dispatch={data.last_decision_status.value if data.last_decision_status else 'none'}."
            ),
            chosen_action={"outcome": outcome.value},
            input_snapshot={
                "missing_roles": list(data.missing_roles),
                "communication_health": data.communication_health.value,
                "attempt_count": data.attempt_count,
                "max_attempts": max_attempts,
                "escalate_after_attempts": escalate_after_attempts,
                "next_check_at": data.next_check_at.isoformat() if data.next_check_at else None,
            },
            state_update={"resolution_outcome": outcome},
        )
