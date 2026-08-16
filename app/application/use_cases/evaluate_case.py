"""EvaluateCaseUseCase — re-evaluates a single case with NO new inbound message, the
application-layer counterpart to a graph pass that only exists because a reply arrived. This
is what makes autonomous follow-up (Phase 6.5 Part 8) possible: a case whose `next_check_at`
has arrived must be able to progress even though nobody replied, and LangGraph's
`wait_for_reply` node can only resume with an actual `InboundMessage` (`interrupt()`'s resume
value) — there is no such message here, and synthesizing a fake one would be worse than not
having this use case at all (see below).

What this does NOT do: touch `receive_message`, `extract_intent`, `extract_entities`, or
`classify_topic`. Those four exist specifically to fold a *new message* into the Conversation
Graph and to run the three permitted extraction/classification LLM tasks on its content —
there is no new message here, so running them would mean either inventing a fake one (which
would pollute the case's real participant/timeline data and silently reclassify its topic
from empty text) or calling the LLM for no reason on every scheduler tick (Part 6.5's "keep
the number of live inference calls reasonable"). Neither is acceptable, so this use case
starts one step later in the same sequence graph.py already defines
(`REASONING_SEQUENCE[3:]`, i.e. from `load_policy` onward) — every one of those nodes is
already written to need only `state.conversation_graph` plus (for calculate_communication_health)
a possibly-`None` `state.current_message`, never a real message body.

How it reuses the deterministic layer: Part 8 says the scheduler "must NOT duplicate
FollowUpPolicy, ResolutionEvaluator, PriorityEngine, ChannelSelectionRules, RoleResolver" —
this use case satisfies that as literally as possible by invoking the *exact same brain node
classes* (LoadPolicyNode, DetectMissingStakeholdersNode, ..., DispatchNode) that graph.py
wires into the LangGraph StateGraph, just called directly as plain Python objects instead of
through LangGraph edges. Zero business logic is reimplemented; only the orchestration differs
(a fixed Python sequence instead of graph edges), and each node still runs its full BrainNode
lifecycle (Decision persisted, Case persisted) exactly as it would inside a real graph pass.
This is not a second reasoning engine — it is the same one, entered at a different point,
for a trigger (time) the graph itself has no edge for.

Checkpoint consistency: every node's persistence step writes `conversation_graph` fields onto
the Case row (see brain/nodes/base.py) — so the Case row is always left correct. But the
LangGraph Postgres checkpoint for this case's thread (still paused inside `wait_for_reply`) is
NOT touched by that — it was written once, at the last real pause, and stays exactly as it
was until something calls `update_state()` on it. If a real reply arrives later and resumes
that stale checkpoint, `wait_for_reply`'s own conversation_graph_update is `{}` (see
wait_for_reply.py), meaning the *stale* pre-sweep values (attempt_count, next_check_at,
communication_health, priority) would be written straight back onto the Case row, silently
erasing every scheduler-driven follow-up that happened since. `compiled_graph` (optional here)
exists to prevent exactly that: after processing, `_sync_checkpoint()` calls the same public
`update_state()` LangGraph API the test suite already uses to simulate cooldown expiry
(tests/integration/test_brain_graph.py), writing this use case's final `conversation_graph`
onto the checkpoint so the next real resume starts from current, not stale, state. Passing
`compiled_graph=None` (e.g. from a unit test using FakeCaseRepository with no real graph)
simply skips this step — the Case row is still correct, only the checkpoint sync is skipped.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import LLMPort
from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.brain.nodes.calculate_communication_health import CalculateCommunicationHealthNode
from app.brain.nodes.calculate_priority import CalculatePriorityNode
from app.brain.nodes.create_decision import CreateDecisionNode
from app.brain.nodes.detect_missing_stakeholders import DetectMissingStakeholdersNode
from app.brain.nodes.dispatch import DispatchNode
from app.brain.nodes.escalate import EscalateNode
from app.brain.nodes.generate_message import GenerateMessageNode
from app.brain.nodes.load_policy import LoadPolicyNode
from app.brain.nodes.resolution_evaluator import ResolutionEvaluatorNode
from app.brain.nodes.resolve_case import ResolveCaseNode
from app.brain.nodes.select_channel import SelectChannelNode
from app.brain.state import AgentState, ConversationGraphState, ParticipantState
from app.domain.entities.case import Case
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.channel_selection_rules import ChannelSelectionRules
from app.domain.services.policy_loader import PolicyLoader
from app.domain.services.role_directory_loader import RoleDirectory
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.resolution_outcome import ResolutionOutcome

logger = logging.getLogger(__name__)

DEFAULT_POLICY_PACK_PATH = "policies/software.yaml"


class EvaluateCaseUseCase:
    def __init__(
        self,
        case_repository: CaseRepositoryPort,
        llm_port: LLMPort,
        dispatch_use_case: DispatchMessageUseCase,
        *,
        policy_loader: PolicyLoader | None = None,
        policy_pack_path: str = DEFAULT_POLICY_PACK_PATH,
        channel_registry: ChannelRegistry | None = None,
        channel_selection_rules: ChannelSelectionRules | None = None,
        role_resolver: RoleResolver | None = None,
        role_directory: RoleDirectory | None = None,
        compiled_graph: CompiledStateGraph | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._compiled_graph = compiled_graph
        self._clock = clock

        policy_loader = policy_loader or PolicyLoader()
        channel_registry = channel_registry or ChannelRegistry()
        role_resolver = role_resolver or RoleResolver(channel_registry)

        # Same node classes graph.py wires into the LangGraph StateGraph — see module
        # docstring for why calling them directly here duplicates zero business logic.
        self._load_policy = LoadPolicyNode(case_repository, policy_loader, policy_pack_path)
        self._detect_missing_stakeholders = DetectMissingStakeholdersNode(case_repository)
        self._calculate_communication_health = CalculateCommunicationHealthNode(
            case_repository, clock=clock
        )
        self._calculate_priority = CalculatePriorityNode(case_repository)
        self._resolution_evaluator = ResolutionEvaluatorNode(case_repository, clock=clock)
        self._escalate = EscalateNode(case_repository)
        self._select_channel = SelectChannelNode(
            case_repository,
            channel_selection_rules,
            channel_registry,
            role_resolver,
            role_directory,
        )
        self._generate_message = GenerateMessageNode(case_repository, llm_port)
        self._create_decision = CreateDecisionNode(case_repository)
        self._dispatch = DispatchNode(case_repository, dispatch_use_case)
        self._resolve_case = ResolveCaseNode(case_repository)

    def evaluate(self, case: Case) -> ResolutionOutcome:
        """Runs one message-less reasoning pass for `case` and returns what it decided.
        Every node along the way persists its own Decision + updated Case fields as it
        always does (BrainNode's lifecycle) — the return value is for the caller's own
        logging/observability, not something further action is conditioned on here."""
        state = AgentState(conversation_graph=_hydrate(case), current_message=None)

        state = self._apply(self._load_policy, state)
        state = self._apply(self._detect_missing_stakeholders, state)
        state = self._apply(self._calculate_communication_health, state)
        state = self._apply(self._calculate_priority, state)
        state = self._apply(self._resolution_evaluator, state)

        outcome = state.resolution_outcome
        if outcome is None:
            raise ValueError("resolution_evaluator did not set state.resolution_outcome")

        if outcome == ResolutionOutcome.FOLLOW_UP:
            state = self._send(state)
        elif outcome == ResolutionOutcome.ESCALATE:
            state = self._apply(self._escalate, state)
            state = self._send(state)
        elif outcome == ResolutionOutcome.RESOLVED:
            state = self._apply(self._resolve_case, state)
        # WAIT: nothing further to do this tick — see graph.py's own routing map, mirrored
        # here (mostly unreachable in practice: list_due_for_followup only returns cases
        # whose cooldown has already expired, which is precisely _should_follow_up's trigger).

        self._sync_checkpoint(state.conversation_graph)
        return outcome

    def _send(self, state: AgentState) -> AgentState:
        """The shared "compose and send" chain — mirrors graph.py's SEND_SEQUENCE (minus
        wait_for_reply, which has no meaning outside a real LangGraph pause)."""
        state = self._apply(self._select_channel, state)
        state = self._apply(self._generate_message, state)
        state = self._apply(self._create_decision, state)
        state = self._apply(self._dispatch, state)
        return state

    @staticmethod
    def _apply(node: Callable[[AgentState], dict[str, Any]], state: AgentState) -> AgentState:
        return replace(state, **node(state))

    def _sync_checkpoint(self, graph_state: ConversationGraphState) -> None:
        if self._compiled_graph is None:
            return
        thread_config: dict[str, Any] = {"configurable": {"thread_id": str(graph_state.case_id)}}
        try:
            self._compiled_graph.update_state(thread_config, {"conversation_graph": graph_state})
        except Exception:
            # Never let a checkpoint-sync failure take down the sweep tick or hide that this
            # case's follow-up genuinely happened (the Case row above is already correct) —
            # log loudly instead so it's visible without corrupting an already-successful
            # dispatch. A subsequent real reply resuming from a stale checkpoint after this is
            # the known, documented consequence — see module docstring.
            logger.exception(
                "Failed to sync LangGraph checkpoint for case %s after a scheduler-driven "
                "follow-up — the case was still updated correctly; a future real reply may "
                "resume from a stale checkpoint.",
                graph_state.case_id,
            )


def _hydrate(case: Case) -> ConversationGraphState:
    """Builds the ConversationGraphState a graph pass would have, from a persisted Case —
    the "hydrating one of these from a Case" job brain/state.py's docstring always described
    this use case as owning."""
    return ConversationGraphState(
        case_id=case.id,
        topic=case.topic,
        participants=[
            ParticipantState(
                id=p.id, name=p.name, role=p.role, email=p.email, telegram_handle=p.telegram_handle
            )
            for p in case.participants
        ],
        channels_used=list(case.channels_used),
        required_roles=list(case.required_roles),
        missing_roles=list(case.missing_roles),
        communication_health=case.communication_health,
        priority=case.priority,
        resolution_status=case.resolution_status,
        attempt_count=case.attempt_count,
        next_check_at=case.next_check_at,
        timeline=list(case.timeline),
    )
