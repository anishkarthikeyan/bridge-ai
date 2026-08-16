"""ExtractEntitiesNode — node 3. LLM. Extracts people, mentioned roles, and dates from the
current message via LLMPort. Transient result (state.extracted_entities) — DetectMissing
StakeholdersNode (node 6) reads the case's structured participants for role coverage, not
this node's free-text extraction; this is supplementary signal for the Decision audit trail,
not a Conversation Graph write.
"""

from __future__ import annotations

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import LLMPort
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState


class ExtractEntitiesNode(BrainNode):
    node_name = "extract_entities"

    def __init__(self, case_repository: CaseRepositoryPort, llm_port: LLMPort) -> None:
        super().__init__(case_repository)
        self._llm_port = llm_port

    def execute(self, state: AgentState) -> NodeResult:
        message = state.current_message
        if message is None:
            raise ValueError("extract_entities requires state.current_message to be set")

        result = self._llm_port.extract_entities(message.body)

        return NodeResult(
            reasoning_summary=(
                f"LLM extracted {len(result.people)} people, {len(result.mentioned_roles)} "
                f"mentioned role(s), {len(result.dates)} date(s) from the message."
            ),
            chosen_action={
                "people": list(result.people),
                "mentioned_roles": list(result.mentioned_roles),
                "dates": list(result.dates),
            },
            input_snapshot={"message_body": message.body},
            state_update={"extracted_entities": result},
        )
