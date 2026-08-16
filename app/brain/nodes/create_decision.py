"""CreateDecisionNode — node 11. Deterministic. Synthesizes the single outbound-action
Decision — recipient (name + address), channel, message, priority — from what nodes 6-10
already computed. `recipient_address` (Phase 5) is what makes this Decision's chosen_action
actually dispatchable: DispatchMessageUseCase builds an OutboundAction straight from it, and
an OutboundAction's Recipient needs a concrete channel identity, not just a name. `topic`
(Phase 6 fix) is what lets DispatchMessageUseCase look up the *right* policy pack entry for
cooldown timing — chosen_action never carried it before, so dispatch was silently falling
back to the default communication rules for every case regardless of its real topic; this
was undetected because no earlier test asserted the exact next_check_at value.

Every other node in this graph persists a Decision too (the base class's lifecycle applies
uniformly), but those record completed internal reasoning steps and default to
DecisionStatus.SUCCESS. This node's Decision is different in kind: it records an action not
yet carried out, so it is the one node that overrides status to PENDING. That PENDING record
is what the dispatch node (Phase 6) finds, executes, and transitions to
EXECUTING -> SUCCESS/FAILED — see architecture doc Change 1.

`decision_id` (Phase 6) is generated here, not left to BrainNode's default uuid4(), so it can
travel forward via `state.pending_decision_id` to the dispatch node, which needs this exact
id to look the Decision back up through the case repository.
"""

from __future__ import annotations

from uuid import uuid4

from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.decision_status import DecisionStatus


class CreateDecisionNode(BrainNode):
    node_name = "create_decision"

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph
        channel = state.selected_channel
        message = state.generated_message

        if channel is None or message is None:
            raise ValueError(
                "create_decision requires state.selected_channel and state.generated_message "
                "to be set (run select_channel and generate_message first)"
            )

        recipient_name, recipient_address = self._recipient(state, channel)
        decision_id = uuid4()

        return NodeResult(
            reasoning_summary=(
                f"Decided to send a {channel.value} message to {recipient_name} "
                f"(priority={graph.priority.value}); awaiting dispatch."
            ),
            chosen_action={
                "action": "send_message",
                "channel": channel.value,
                "recipient_name": recipient_name,
                "recipient_address": recipient_address,
                "message": message,
                "priority": graph.priority.value,
                "missing_roles": list(graph.missing_roles),
                "topic": graph.topic,
            },
            input_snapshot={
                "topic": graph.topic,
                "communication_health": graph.communication_health.value,
            },
            status=DecisionStatus.PENDING,
            decision_id=decision_id,
            state_update={"pending_decision_id": decision_id},
        )

    @staticmethod
    def _recipient(state: AgentState, channel: Channel) -> tuple[str | None, str | None]:
        resolution = state.role_resolution
        if resolution is not None and resolution.resolved and resolution.participant is not None:
            return resolution.participant.name, resolution.address

        message = state.current_message
        if message is None:
            return None, None
        address = (
            message.sender.email if channel == Channel.EMAIL else message.sender.telegram_handle
        )
        return message.sender.name, address
