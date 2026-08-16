"""ExtractIntentNode — node 2. LLM. Classifies the current message's intent from a closed
label set via LLMPort — one of the four permitted LLM tasks (architecture doc §3). The
result is transient (state.extracted_intent); it does not itself change the Conversation
Graph, so conversation_graph_update is empty — only the Decision records what the model saw
and returned.
"""

from __future__ import annotations

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import LLMPort
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState


class ExtractIntentNode(BrainNode):
    node_name = "extract_intent"

    def __init__(self, case_repository: CaseRepositoryPort, llm_port: LLMPort) -> None:
        super().__init__(case_repository)
        self._llm_port = llm_port

    def execute(self, state: AgentState) -> NodeResult:
        message = state.current_message
        if message is None:
            raise ValueError("extract_intent requires state.current_message to be set")

        result = self._llm_port.extract_intent(message.body)

        return NodeResult(
            reasoning_summary=(
                f"LLM classified intent as '{result.intent}' (confidence={result.confidence:.2f})."
            ),
            chosen_action={"intent": result.intent, "confidence": result.confidence},
            input_snapshot={"message_body": message.body},
            confidence=result.confidence,
            state_update={"extracted_intent": result},
        )
