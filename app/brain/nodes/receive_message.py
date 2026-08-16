"""ReceiveMessageNode — node 1. Takes the InboundMessage already staged in
`state.current_message` (by whatever invoked the graph, or by WaitForReplyNode on resume)
and merges its sender + cc into the case's participant list.

Also ensures a Conversation row exists for (channel, external_thread_ref) — a gap that
predates Phase 6 but was only caught now, testing against the real repository end to end
for the first time: nothing previously ever called `add_conversation`, so
`find_by_conversation_ref` (the "find-or-open a case by thread ref" lookup
IngestInboundMessageUseCase has depended on since Phase 5) could never actually find an
existing case on a reply — every reply silently opened a new one instead. Checked via
`find_by_conversation_ref` itself rather than a new port method: if it already resolves to
this case, a Conversation exists; if it returns None, create one.

No actual channel parsing happens here — turning a raw Caspian/email/Telegram payload into
an InboundMessage is the (still out-of-scope) adapters' job. This node only does the
deterministic, structural work of folding an already-normalized message into the
Conversation Graph; there is no LLM involvement.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.application.dto.inbound_message import InboundMessage, MessageParticipant
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState, ParticipantState
from app.domain.entities.conversation import Conversation
from app.domain.entities.participant import Participant
from app.domain.value_objects.participant_source import ParticipantSource


class ReceiveMessageNode(BrainNode):
    node_name = "receive_message"

    def execute(self, state: AgentState) -> NodeResult:
        message = state.current_message
        if message is None:
            raise ValueError("receive_message requires state.current_message to be set")

        graph = state.conversation_graph
        known = {(p.name, p.email) for p in graph.participants}

        new_states: list[ParticipantState] = []
        for candidate in (message.sender, *message.cc):
            key = (candidate.name, candidate.email)
            if key in known:
                continue
            known.add(key)
            persisted = self._case_repository.add_participant(
                graph.case_id, _to_participant_entity(graph.case_id, candidate)
            )
            new_states.append(_to_participant_state(persisted))

        merged_participants = [*graph.participants, *new_states]

        channels_used = graph.channels_used
        if message.channel not in channels_used:
            channels_used = [*channels_used, message.channel]

        conversation_created = self._ensure_conversation(graph.case_id, message)

        return NodeResult(
            reasoning_summary=(
                f"Received message on {message.channel.value} from {message.sender.name}; "
                f"merged {len(new_states)} new participant(s) into the case."
            ),
            chosen_action={
                "channel": message.channel.value,
                "new_participants": [p.name for p in new_states],
                "conversation_created": conversation_created,
            },
            input_snapshot={"sender": message.sender.name, "cc": [c.name for c in message.cc]},
            conversation_graph_update={
                "participants": merged_participants,
                "channels_used": channels_used,
            },
        )

    def _ensure_conversation(self, case_id: UUID, message: InboundMessage) -> bool:
        if message.external_thread_ref is None:
            return False
        existing = self._case_repository.find_by_conversation_ref(
            message.channel.value, message.external_thread_ref
        )
        if existing is not None:
            return False
        self._case_repository.add_conversation(
            case_id,
            Conversation(
                id=uuid4(),
                case_id=case_id,
                channel=message.channel,
                external_thread_ref=message.external_thread_ref,
            ),
        )
        return True


def _to_participant_entity(case_id: UUID, candidate: MessageParticipant) -> Participant:
    return Participant(
        id=uuid4(),
        case_id=case_id,
        name=candidate.name,
        role=candidate.role,
        email=candidate.email,
        telegram_handle=candidate.telegram_handle,
        source=ParticipantSource.EXPLICIT,
    )


def _to_participant_state(participant: Participant) -> ParticipantState:
    return ParticipantState(
        id=participant.id,
        name=participant.name,
        role=participant.role,
        email=participant.email,
        telegram_handle=participant.telegram_handle,
    )
