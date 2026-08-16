"""CalculateCommunicationHealthNode — node 7. Deterministic. Scores the case 0-100 via
CommunicationHealthCalculator (app/domain/services/, Phase 3) and bands it into the
CommunicationHealth enum written onto the Conversation Graph.

`now` is constructor-injected (defaulting to the real clock) rather than read internally —
same reasoning as the calculator itself: a node that reads the system clock directly can't
be tested deterministically, and "every node must be deterministic except LLM nodes" applies
to this one.

Uses `current_message.received_at` as a proxy for "last conversation activity" — the most
recent inbound message is the most recent signal of the other side engaging. There's no
richer activity signal available at this phase (no message log lookup — that's
MessageRepositoryPort, not wired into the brain yet); flagged in the Phase 5 checklist.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.services.communication_health_calculator import (
    CommunicationHealthCalculator,
    CommunicationHealthInput,
)


class CalculateCommunicationHealthNode(BrainNode):
    node_name = "calculate_communication_health"

    def __init__(
        self,
        case_repository: CaseRepositoryPort,
        calculator: CommunicationHealthCalculator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(case_repository)
        self._calculator = calculator or CommunicationHealthCalculator()
        self._clock = clock

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph
        now = self._clock()
        last_activity_at = state.current_message.received_at if state.current_message else None

        score = self._calculator.score(
            CommunicationHealthInput(
                missing_roles_count=len(graph.missing_roles),
                attempt_count=graph.attempt_count,
                next_check_at=graph.next_check_at,
                last_activity_at=last_activity_at,
                now=now,
            )
        )
        health_state = CommunicationHealthCalculator.to_health_state(score)

        return NodeResult(
            reasoning_summary=f"Communication health score: {score}/100 -> {health_state.value}.",
            chosen_action={"score": score, "state": health_state.value},
            input_snapshot={
                "missing_roles_count": len(graph.missing_roles),
                "attempt_count": graph.attempt_count,
                "next_check_at": graph.next_check_at.isoformat() if graph.next_check_at else None,
            },
            state_update={"communication_health_score": score},
            conversation_graph_update={"communication_health": health_state},
        )
