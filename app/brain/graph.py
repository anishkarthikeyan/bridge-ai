"""The AI Brain's LangGraph wiring — compiles every node into one StateGraph over AgentState
(app/brain/state.py). Checkpointing is deliberately not this module's concern —
`build_graph()` returns an *uncompiled* StateGraph; the caller compiles it with whichever
checkpointer fits the context (Postgres in production, see checkpointer.py; in-memory for
tests) via `graph.compile(checkpointer=...)`.

Phase 6 replaces the Phase 4/5 unconditional `resume_case -> receive_message` loop with a
real termination condition. The shape:

    receive_message -> extract_intent -> extract_entities -> classify_topic -> load_policy
    -> detect_missing_stakeholders -> calculate_communication_health -> calculate_priority
    -> resolution_evaluator
         |-- WAIT ------> wait_for_reply
         |-- FOLLOW_UP -> select_channel -> generate_message -> create_decision -> dispatch
         |-- ESCALATE --> escalate -> select_channel -> ... (same send chain as FOLLOW_UP)
         `-- RESOLVED --> resolve_case -> END

    dispatch -> wait_for_reply -> receive_message   (the one cycle: resume re-enters at the
                                                       top so a reply's new participants and
                                                       topic/stakeholder/health/priority are
                                                       always freshly reprocessed before
                                                       resolution_evaluator judges anything)

`resolution_evaluator` sits right after `calculate_priority`, not literally right after
`wait_for_reply` — every path that reaches it, including the very first pass over a brand
new case, has already gone through the full reasoning pipeline, so it is genuinely "the ONLY
decision point after every reply" (architecture doc, Change 1): by the time it runs, the
reply (if any) has already updated missing_roles, communication_health, and priority, not
just been received. See the Phase 6 architectural observations for why placing it literally
between wait_for_reply and receive_message, as the sequence diagram's flattened list might
suggest, would leave it judging stale data from before the reply was processed.

`escalate` and `select_channel` both flow into the same `generate_message -> create_decision
-> dispatch` chain — Change 4's "increase priority / choose escalation participant / possibly
change channel" are satisfied entirely by `escalate` rewriting conversation_graph state
before handing off, not by a second, duplicated send pipeline.

There is now exactly one path to END (`resolve_case`), and `resolution_evaluator`'s ESCALATE
branch guarantees attempt_count eventually forces either RESOLVED or a repeating ESCALATE
cycle that always still pauses at an interrupt each pass — never an unbounded loop within a
single `invoke()` call. See the Phase 6 test suite's "no infinite loop" coverage.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import LLMPort
from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.brain.nodes.calculate_communication_health import CalculateCommunicationHealthNode
from app.brain.nodes.calculate_priority import CalculatePriorityNode
from app.brain.nodes.classify_topic import ClassifyTopicNode
from app.brain.nodes.create_decision import CreateDecisionNode
from app.brain.nodes.detect_missing_stakeholders import DetectMissingStakeholdersNode
from app.brain.nodes.dispatch import DispatchNode
from app.brain.nodes.escalate import EscalateNode
from app.brain.nodes.extract_entities import ExtractEntitiesNode
from app.brain.nodes.extract_intent import ExtractIntentNode
from app.brain.nodes.generate_message import GenerateMessageNode
from app.brain.nodes.load_policy import LoadPolicyNode
from app.brain.nodes.receive_message import ReceiveMessageNode
from app.brain.nodes.resolution_evaluator import ResolutionEvaluatorNode
from app.brain.nodes.resolve_case import ResolveCaseNode
from app.brain.nodes.select_channel import SelectChannelNode
from app.brain.nodes.wait_for_reply import WaitForReplyNode
from app.brain.state import AgentState
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.channel_selection_rules import ChannelSelectionRules
from app.domain.services.communication_health_calculator import CommunicationHealthCalculator
from app.domain.services.policy_loader import PolicyLoader
from app.domain.services.role_directory_loader import RoleDirectory
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.resolution_outcome import ResolutionOutcome
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry

REASONING_SEQUENCE: tuple[str, ...] = (
    "receive_message",
    "extract_intent",
    "extract_entities",
    "classify_topic",
    "load_policy",
    "detect_missing_stakeholders",
    "calculate_communication_health",
    "calculate_priority",
    "resolution_evaluator",
)
"""Every case, every pass, runs this sequence before the ONE decision point. FOLLOW_UP and
ESCALATE both continue into SEND_SEQUENCE below; WAIT short-circuits to wait_for_reply;
RESOLVED short-circuits to resolve_case -> END."""

SEND_SEQUENCE: tuple[str, ...] = (
    "select_channel",
    "generate_message",
    "create_decision",
    "dispatch",
    "wait_for_reply",
)
"""The shared "compose and send" chain — reused by both FOLLOW_UP (direct) and ESCALATE
(via the escalate node first)."""

# add_conditional_edges wants the routing function to return a hashable *key*, and a
# separate path_map translating each possible key to an actual node name — it does not
# accept a routing function that returns node names directly. Keys here are the
# ResolutionOutcome values (plain strings, since ResolutionOutcome is a str Enum).
_RESOLUTION_PATH_MAP: dict[str, str] = {
    ResolutionOutcome.WAIT.value: "wait_for_reply",
    ResolutionOutcome.FOLLOW_UP.value: "select_channel",
    ResolutionOutcome.ESCALATE.value: "escalate",
    ResolutionOutcome.RESOLVED.value: "resolve_case",
}


def _route_resolution(state: AgentState) -> str:
    outcome = state.resolution_outcome
    if outcome is None:
        raise ValueError("resolution_evaluator did not set state.resolution_outcome")
    return outcome.value


def build_graph(
    case_repository: CaseRepositoryPort,
    llm_port: LLMPort,
    channel_adapter_registry: ChannelAdapterRegistry,
    *,
    policy_loader: PolicyLoader | None = None,
    channel_registry: ChannelRegistry | None = None,
    channel_selection_rules: ChannelSelectionRules | None = None,
    communication_health_calculator: CommunicationHealthCalculator | None = None,
    role_resolver: RoleResolver | None = None,
    role_directory: RoleDirectory | None = None,
    dispatch_use_case: DispatchMessageUseCase | None = None,
) -> StateGraph:
    """Builds the uncompiled graph. Every node is constructed once here with its injected
    dependencies — nodes hold no state beyond these, so the same built graph is safe to
    compile once and invoke many times concurrently.
    """
    policy_loader = policy_loader or PolicyLoader()
    dispatch_use_case = dispatch_use_case or DispatchMessageUseCase(
        case_repository, channel_adapter_registry, policy_loader=policy_loader
    )

    graph: StateGraph = StateGraph(AgentState)

    graph.add_node("receive_message", ReceiveMessageNode(case_repository))
    graph.add_node("extract_intent", ExtractIntentNode(case_repository, llm_port))
    graph.add_node("extract_entities", ExtractEntitiesNode(case_repository, llm_port))
    graph.add_node("classify_topic", ClassifyTopicNode(case_repository, llm_port))
    graph.add_node("load_policy", LoadPolicyNode(case_repository, policy_loader))
    graph.add_node("detect_missing_stakeholders", DetectMissingStakeholdersNode(case_repository))
    graph.add_node(
        "calculate_communication_health",
        CalculateCommunicationHealthNode(case_repository, communication_health_calculator),
    )
    graph.add_node("calculate_priority", CalculatePriorityNode(case_repository))
    graph.add_node("resolution_evaluator", ResolutionEvaluatorNode(case_repository))
    graph.add_node("escalate", EscalateNode(case_repository))
    graph.add_node(
        "select_channel",
        SelectChannelNode(
            case_repository,
            channel_selection_rules,
            channel_registry,
            role_resolver,
            role_directory,
        ),
    )
    graph.add_node("generate_message", GenerateMessageNode(case_repository, llm_port))
    graph.add_node("create_decision", CreateDecisionNode(case_repository))
    graph.add_node("dispatch", DispatchNode(case_repository, dispatch_use_case))
    graph.add_node("wait_for_reply", WaitForReplyNode(case_repository))
    graph.add_node("resolve_case", ResolveCaseNode(case_repository))

    graph.add_edge(START, "receive_message")
    for current_node, next_node in zip(REASONING_SEQUENCE, REASONING_SEQUENCE[1:], strict=False):
        graph.add_edge(current_node, next_node)

    graph.add_conditional_edges("resolution_evaluator", _route_resolution, _RESOLUTION_PATH_MAP)

    graph.add_edge("escalate", "select_channel")
    for current_node, next_node in zip(SEND_SEQUENCE, SEND_SEQUENCE[1:], strict=False):
        graph.add_edge(current_node, next_node)

    graph.add_edge("wait_for_reply", "receive_message")
    graph.add_edge("resolve_case", END)

    return graph
