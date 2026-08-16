"""ResolveCaseNode — the RESOLVED terminal action (architecture doc, Phase 6). Deterministic:
marks the case's resolution_status, persists that as its own Decision (the "final Decision"
the spec calls for) and updated state via the normal BrainNode lifecycle, and routes to END
— see graph.py, the only node this graph connects directly to END.
"""

from __future__ import annotations

from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.value_objects.resolution_state import ResolutionState


class ResolveCaseNode(BrainNode):
    node_name = "resolve_case"

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph

        return NodeResult(
            reasoning_summary=(
                f"Case {graph.case_id} resolved: no missing stakeholders, "
                f"communication health {graph.communication_health.value}, "
                f"{graph.attempt_count} attempt(s)."
            ),
            chosen_action={
                "resolution_status": ResolutionState.RESOLVED.value,
                "attempt_count": graph.attempt_count,
            },
            input_snapshot={
                "missing_roles": list(graph.missing_roles),
                "communication_health": graph.communication_health.value,
            },
            conversation_graph_update={"resolution_status": ResolutionState.RESOLVED},
        )
