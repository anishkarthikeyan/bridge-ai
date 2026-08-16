"""ClassifyTopicNode — node 4. LLM. Maps the current message to a topic label via LLMPort.
Unlike intent/entities, the topic IS written into the Conversation Graph (`topic`) — it's
what LoadPolicyNode (node 5) looks up next. The model only produces a label from free text;
whether that label matches a known policy, and what follows if it doesn't, is TopicResolver's
job (deterministic, node 5) — this node never validates the topic against the policy pack.
"""

from __future__ import annotations

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import LLMPort
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState


class ClassifyTopicNode(BrainNode):
    node_name = "classify_topic"

    def __init__(self, case_repository: CaseRepositoryPort, llm_port: LLMPort) -> None:
        super().__init__(case_repository)
        self._llm_port = llm_port

    def execute(self, state: AgentState) -> NodeResult:
        message = state.current_message
        if message is None:
            raise ValueError("classify_topic requires state.current_message to be set")

        result = self._llm_port.classify_topic(message.body)

        return NodeResult(
            reasoning_summary=(
                f"LLM classified topic as '{result.topic}' (confidence={result.confidence:.2f})."
            ),
            chosen_action={"topic": result.topic, "confidence": result.confidence},
            input_snapshot={"message_body": message.body},
            confidence=result.confidence,
            state_update={"topic_classification": result},
            conversation_graph_update={"topic": result.topic},
        )
