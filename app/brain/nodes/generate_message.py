"""GenerateMessageNode — node 10. LLM. Generates outbound message content only — the last of
the four permitted LLM tasks. It never decides who, when, or which channel; those were
already fixed by nodes 6-9 before this one runs, and are only passed in as context.

`case_summary` is built here with plain string formatting, not by the model — assembling
known facts into a sentence isn't generation, it's just giving the LLM grounded context to
generate from.

Recipient: uses `state.role_resolution.participant` when select_channel resolved a missing
role (Phase 5); falls back to the original sender otherwise — the same two-path split
select_channel itself makes, mirrored here so the message addresses whoever it's actually
being sent to.
"""

from __future__ import annotations

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import LLMPort, MessageGenerationContext
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState


class GenerateMessageNode(BrainNode):
    node_name = "generate_message"

    def __init__(self, case_repository: CaseRepositoryPort, llm_port: LLMPort) -> None:
        super().__init__(case_repository)
        self._llm_port = llm_port

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph
        message = state.current_message
        channel = state.selected_channel

        if channel is None:
            raise ValueError(
                "generate_message requires state.selected_channel to be set "
                "(run select_channel first)"
            )

        resolution = state.role_resolution
        if resolution is not None and resolution.resolved and resolution.participant is not None:
            recipient_name = resolution.participant.name
        else:
            recipient_name = message.sender.name if message else "the case participants"

        case_summary = (
            f"Topic: {graph.topic or 'unclassified'}. "
            f"Missing roles: {graph.missing_roles or 'none'}. "
            f"Priority: {graph.priority.value}."
        )

        context = MessageGenerationContext(
            topic=graph.topic,
            missing_roles=tuple(graph.missing_roles),
            channel=channel.value,
            recipient_name=recipient_name,
            case_summary=case_summary,
        )
        text = self._llm_port.generate_message(context)

        return NodeResult(
            reasoning_summary=f"Generated a {channel.value} message for {recipient_name}.",
            chosen_action={"channel": channel.value, "recipient": recipient_name, "message": text},
            input_snapshot={"case_summary": case_summary},
            state_update={"generated_message": text},
        )
