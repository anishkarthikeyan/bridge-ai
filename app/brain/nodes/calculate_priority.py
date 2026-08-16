"""CalculatePriorityNode — node 8. Deterministic. Runs PriorityEngine
(app/domain/services/, Phase 3) over the topic's baseline priority, the missing-role gap,
the communication health score, and the policy pack's escalation threshold, and writes the
result onto the Conversation Graph.

Falls back to Priority.MEDIUM when the topic has no policy entry (policy_topic is None) —
same "degrade, don't fail" behavior as LoadPolicyNode for an out-of-pack topic.
"""

from __future__ import annotations

from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.services.priority_engine import PriorityEngine, PriorityInput
from app.domain.value_objects.priority import Priority


class CalculatePriorityNode(BrainNode):
    node_name = "calculate_priority"

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph
        policy_topic = state.policy_topic
        health_score = state.communication_health_score
        if health_score is None:
            raise ValueError(
                "calculate_priority requires state.communication_health_score to be set "
                "(run calculate_communication_health first)"
            )

        base_priority = policy_topic.priority if policy_topic else Priority.MEDIUM
        escalation_threshold_reached = bool(
            policy_topic
            and graph.attempt_count >= policy_topic.escalation_rules.escalate_after_attempts
        )

        priority = PriorityEngine().calculate(
            PriorityInput(
                base_priority=base_priority,
                required_roles_count=len(graph.required_roles),
                missing_roles_count=len(graph.missing_roles),
                communication_health_score=health_score,
                escalation_threshold_reached=escalation_threshold_reached,
            )
        )

        return NodeResult(
            reasoning_summary=(
                f"Priority: {priority.value} (base={base_priority.value}, "
                f"health_score={health_score}, escalation_threshold_reached="
                f"{escalation_threshold_reached})."
            ),
            chosen_action={"priority": priority.value},
            input_snapshot={
                "base_priority": base_priority.value,
                "missing_roles_count": len(graph.missing_roles),
                "required_roles_count": len(graph.required_roles),
                "communication_health_score": health_score,
                "escalation_threshold_reached": escalation_threshold_reached,
            },
            conversation_graph_update={"priority": priority},
        )
