"""LoadPolicyNode — node 5. Deterministic. Resolves the classified topic against a loaded
policy pack via PolicyLoader + TopicResolver (both from app/domain/services/, Phase 3) and
writes the resulting required_roles into the Conversation Graph.

Uses resolve_or_none rather than resolve(): a topic outside the pack (e.g. the
customer_escalation demo scenario) degrades to an empty required_roles list rather than
failing the whole case — see architecture doc §2 for why that's the intended behavior, not
an error condition.
"""

from __future__ import annotations

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState
from app.domain.services.policy_loader import PolicyLoader
from app.domain.services.topic_resolver import TopicResolver

DEFAULT_POLICY_PACK_PATH = "policies/software.yaml"


class LoadPolicyNode(BrainNode):
    node_name = "load_policy"

    def __init__(
        self,
        case_repository: CaseRepositoryPort,
        policy_loader: PolicyLoader,
        policy_pack_path: str = DEFAULT_POLICY_PACK_PATH,
    ) -> None:
        super().__init__(case_repository)
        self._policy_loader = policy_loader
        self._policy_pack_path = policy_pack_path

    def execute(self, state: AgentState) -> NodeResult:
        topic = state.conversation_graph.topic

        pack = self._policy_loader.load(self._policy_pack_path)
        policy_topic = pack.get_topic(topic) if topic else None

        required_roles = list(policy_topic.required_roles) if policy_topic else []

        if policy_topic is not None:
            summary = (
                f"Resolved '{topic}' against {pack.industry_pack} v{pack.version}: "
                f"requires {required_roles}."
            )
        else:
            summary = (
                f"'{topic}' has no entry in {pack.industry_pack} v{pack.version} — "
                "proceeding with no required roles."
            )

        return NodeResult(
            reasoning_summary=summary,
            chosen_action={"topic": topic, "required_roles": required_roles},
            input_snapshot={"industry_pack": pack.industry_pack, "version": pack.version},
            state_update={"policy_topic": policy_topic},
            conversation_graph_update={"required_roles": required_roles},
        )
