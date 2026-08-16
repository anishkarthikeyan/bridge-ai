"""IngestInboundMessageUseCase — Inbound Routing (architecture doc, Phase 5 item 3). Takes a
canonical InboundMessage (already parsed by a ChannelPort adapter) and either resumes an
existing case's paused brain graph or starts a new one — the "find-or-open a case by thread
ref" behavior the architecture called for since Phase 1, now with a real graph behind it.

The only caller of app/brain/runner.py's start_case/resume_case outside of tests — this is
where the brain is actually invoked from a live inbound event.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.graph.state import CompiledStateGraph

from app.application.dto.inbound_message import InboundMessage
from app.application.ports.case_repository_port import CaseRepositoryPort
from app.brain.runner import resume_case, start_case
from app.brain.state import AgentState, ConversationGraphState
from app.domain.entities.case import Case


class IngestInboundMessageUseCase:
    def __init__(
        self, case_repository: CaseRepositoryPort, compiled_graph: CompiledStateGraph
    ) -> None:
        self._case_repository = case_repository
        self._compiled_graph = compiled_graph

    def handle(self, message: InboundMessage) -> dict[str, Any]:
        existing_case = None
        if message.external_thread_ref:
            existing_case = self._case_repository.find_by_conversation_ref(
                message.channel.value, message.external_thread_ref
            )

        if existing_case is not None:
            return resume_case(self._compiled_graph, existing_case.id, message)

        case = self._case_repository.add(Case(id=uuid4()))
        initial_state = AgentState(
            conversation_graph=ConversationGraphState(case_id=case.id),
            current_message=message,
        )
        return start_case(self._compiled_graph, initial_state)
