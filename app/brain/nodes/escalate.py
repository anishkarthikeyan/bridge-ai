"""EscalateNode — deterministic (architecture doc, Phase 6 Change 4). No AI: "increase
priority," "choose escalation participant," and "possibly change communication channel" are
all satisfied by manipulating conversation_graph, not by any new resolution logic of its
own — this node deliberately does *not* call RoleResolver or ChannelRegistry itself.

Instead it reorders `missing_roles` to put the policy pack's `escalation_rules.escalate_to_roles`
first (deduped against whatever was already missing) and forces `priority` to HIGH, then
routes to the existing `select_channel` node — which already knows how to resolve a role via
RoleResolver and pick a channel via ChannelRegistry (Phase 5). Reusing it here means
"possibly change communication channel" falls out naturally from the new priority and new
target role, with no new channel-selection logic duplicated.

If the topic has no policy entry (no escalate_to_roles to prioritize), missing_roles is left
as-is — select_channel's existing fallback (reply to the original sender, now at HIGH
priority) still applies.

Note: this can put a role into `missing_roles` that isn't actually structurally missing
(e.g. escalating to Finance for visibility even though Finance already replied) — that's a
deliberate, single-pass repurposing of the field as "who this escalation message targets,"
not a corruption of the real state: detect_missing_stakeholders recomputes missing_roles
from scratch on the very next pass, so any such entry is corrected before it could affect a
resolution decision.
"""

from __future__ import annotations

from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.value_objects.priority import Priority


class EscalateNode(BrainNode):
    node_name = "escalate"

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph
        policy_topic = state.policy_topic
        escalate_to_roles = (
            list(policy_topic.escalation_rules.escalate_to_roles) if policy_topic else []
        )

        reordered: list[str] = []
        for role in [*escalate_to_roles, *graph.missing_roles]:
            if role and role not in reordered:
                reordered.append(role)

        return NodeResult(
            reasoning_summary=(
                f"Escalating case {graph.case_id}: priority {graph.priority.value} -> high; "
                f"targeting {reordered or 'the original sender'} first."
            ),
            chosen_action={
                "previous_priority": graph.priority.value,
                "escalate_to_roles": escalate_to_roles,
                "reordered_missing_roles": reordered,
            },
            input_snapshot={"attempt_count": graph.attempt_count},
            conversation_graph_update={"priority": Priority.HIGH, "missing_roles": reordered},
        )
