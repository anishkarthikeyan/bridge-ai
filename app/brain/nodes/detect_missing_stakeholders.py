"""DetectMissingStakeholdersNode — node 6. Deterministic. Diffs the case's current
participant roles against required_roles via StakeholderEngine (app/domain/services/, Phase
3) and writes missing_roles into the Conversation Graph. This is the machine-checkable
version of "a conversation that should exist but doesn't" — see architecture doc §2.
"""

from __future__ import annotations

from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.services.stakeholder_engine import StakeholderEngine


class DetectMissingStakeholdersNode(BrainNode):
    node_name = "detect_missing_stakeholders"

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph
        participant_roles = [p.role for p in graph.participants]

        evaluation = StakeholderEngine().evaluate(participant_roles, graph.required_roles)

        return NodeResult(
            reasoning_summary=(
                f"Present: {list(evaluation.present_roles)}; "
                f"missing: {list(evaluation.missing_roles)}."
            ),
            chosen_action={
                "present_roles": list(evaluation.present_roles),
                "missing_roles": list(evaluation.missing_roles),
            },
            input_snapshot={
                "participant_roles": [r for r in participant_roles if r],
                "required_roles": graph.required_roles,
            },
            conversation_graph_update={"missing_roles": list(evaluation.missing_roles)},
        )
