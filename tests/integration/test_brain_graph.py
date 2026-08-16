"""Graph-level proof, constructed directly (no Caspian layer) — complements
test_end_to_end_communication.py, which covers WAIT and RESOLVED via real inbound events.
This file covers the two branches that need deliberately manipulated case state to trigger
cleanly: FOLLOW_UP (cooldown expiry) and ESCALATE (attempt threshold) — plus the structural
guarantee that a single `invoke()` call can never run unboundedly.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from app.application.dto.inbound_message import InboundMessage, MessageParticipant
from app.brain.graph import REASONING_SEQUENCE, SEND_SEQUENCE, build_graph
from app.brain.runner import resume_case, start_case
from app.brain.state import AgentState, ConversationGraphState
from app.domain.entities.case import Case
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.role_directory_loader import RoleDirectoryLoader
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.priority import Priority
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.outbound.caspian_gateway import CaspianGateway
from tests.unit.brain.fakes import FakeCaseRepository, FakeLLMPort

# Every node from receive_message through resolution_evaluator runs on every single pass;
# FOLLOW_UP/ESCALATE continue into SEND_SEQUENCE, WAIT and RESOLVED short-circuit out of it.
FULL_SEND_PASS = (*REASONING_SEQUENCE, *SEND_SEQUENCE)

# What actually gets *persisted* on the pausing call: everything up to but excluding
# wait_for_reply itself — its own Decision only persists on the *resuming* call, since
# interrupt() never returns (and so BrainNode's post-execute persistence never runs) on the
# call that pauses. See wait_for_reply.py.
PERSISTED_BEFORE_PAUSE = (*REASONING_SEQUENCE, *SEND_SEQUENCE[:-1])
assert SEND_SEQUENCE[-1] == "wait_for_reply"

_ROLE_DIRECTORY = RoleDirectoryLoader().load("policies/role_directory.yaml")


def _build_graph(repo: FakeCaseRepository, llm: FakeLLMPort):
    gateway = CaspianGateway(LocalCaspianClient())
    registry = ChannelAdapterRegistry(
        {Channel.EMAIL: EmailAdapter(gateway), Channel.TELEGRAM: TelegramAdapter(gateway)}
    )
    channel_registry = ChannelRegistry(available_channels={Channel.EMAIL, Channel.TELEGRAM})
    return build_graph(
        repo,
        llm,
        registry,
        channel_registry=channel_registry,
        role_resolver=RoleResolver(channel_registry),
        role_directory=_ROLE_DIRECTORY,
    ).compile(checkpointer=InMemorySaver())


def _message(body: str, sender_role: str = "Engineer") -> InboundMessage:
    return InboundMessage(
        channel=Channel.EMAIL,
        sender=MessageParticipant(name="Dana Kapoor", email="dana@co.com", role=sender_role),
        cc=(MessageParticipant(name="Priya Sundaram", email="priya@co.com", role="Finance"),),
        subject="Changing the refund flow to settle same-day",
        body=body,
        received_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
    )


def test_first_pass_reasons_dispatches_and_pauses() -> None:
    repo = FakeCaseRepository()
    llm = FakeLLMPort()  # default topic: payment_system
    case_id = repo.add(Case(id=uuid4())).id
    compiled = _build_graph(repo, llm)

    result = start_case(
        compiled,
        AgentState(
            conversation_graph=ConversationGraphState(case_id=case_id),
            current_message=_message("Wanted Finance looped in before this ships."),
        ),
    )

    assert "__interrupt__" in result
    ran_nodes = [d.node_name for d in repo.decisions]
    assert ran_nodes == list(PERSISTED_BEFORE_PAUSE)

    graph = result["conversation_graph"]
    assert graph.topic == "payment_system"
    assert graph.missing_roles == ["Security", "Support"]
    assert graph.priority == Priority.HIGH  # payment_system's policy-pack baseline
    assert graph.attempt_count == 1  # dispatch already ran, for real, within this one pass

    # RoleResolver picked John Ortiz (Security, preference_rank 1) — a real email send.
    # create_decision starts PENDING, but dispatch (later in this same pass) transitions it
    # through EXECUTING to SUCCESS — the full Change 1 lifecycle within one pass.
    create_decision = next(d for d in repo.decisions if d.node_name == "create_decision")
    assert create_decision.status.value == "success"
    assert create_decision.chosen_action["recipient_address"] == "john@co.com"
    dispatch_decision = next(d for d in repo.decisions if d.node_name == "dispatch")
    assert dispatch_decision.status.value == "success"
    evaluator_decision = next(d for d in repo.decisions if d.node_name == "resolution_evaluator")
    assert evaluator_decision.chosen_action["outcome"] == "follow_up"  # fresh case, first send


def test_cooldown_expiry_triggers_follow_up_resend() -> None:
    repo = FakeCaseRepository()
    llm = FakeLLMPort(topic="database_migration")  # escalate_after_attempts=2, room for a follow-up
    case_id = repo.add(Case(id=uuid4())).id
    compiled = _build_graph(repo, llm)

    start_case(
        compiled,
        AgentState(
            conversation_graph=ConversationGraphState(case_id=case_id),
            current_message=_message("Migration planned for the weekend.", sender_role="DevOps"),
        ),
    )
    assert repo.get_by_id(case_id).attempt_count == 1
    decisions_before = len(repo.decisions)

    # Force cooldown to have expired. Mutating repo.cases[case_id] directly would NOT be
    # enough — the graph resumes from its own checkpointed AgentState snapshot, independent
    # of the repository, so the checkpoint itself must be updated via update_state().
    thread_config = {"configurable": {"thread_id": str(case_id)}}
    checkpointed_graph = compiled.get_state(thread_config).values["conversation_graph"]
    compiled.update_state(
        thread_config,
        {
            "conversation_graph": replace(
                checkpointed_graph, next_check_at=datetime.now(UTC) - timedelta(hours=1)
            )
        },
    )

    # Wei Zhang (DBA) — one of the two missing roles — replies. QA is still missing, so this
    # cannot resolve the case; cooldown being expired must drive a FOLLOW_UP resend instead.
    reply = InboundMessage(
        channel=Channel.EMAIL,
        sender=MessageParticipant(name="Wei Zhang", email="wei@co.com", role="DBA"),
        body="Looks fine from the DB side.",
        received_at=datetime.now(UTC),
    )
    result = resume_case(compiled, case_id, reply)

    assert "__interrupt__" in result
    case = repo.get_by_id(case_id)
    assert case.missing_roles == ["QA"]  # DBA resolved, QA still isn't
    assert case.attempt_count == 2  # a second message really was dispatched

    new_nodes = [d.node_name for d in repo.decisions[decisions_before:]]
    assert new_nodes[0] == "wait_for_reply"  # the resumed pause
    evaluator_decision = next(
        d for d in repo.decisions[decisions_before:] if d.node_name == "resolution_evaluator"
    )
    assert evaluator_decision.chosen_action["outcome"] == "follow_up"
    assert new_nodes.count("dispatch") == 1  # exactly one new send this resume
    assert new_nodes[-1] == "dispatch"  # sent, then paused — wait_for_reply's own decision
    # doesn't persist until the *next* resume (see PERSISTED_BEFORE_PAUSE above)


def test_attempt_threshold_triggers_escalation() -> None:
    repo = FakeCaseRepository()
    llm = FakeLLMPort()  # payment_system: escalate_after_attempts=1 — triggers after just one send
    case_id = repo.add(Case(id=uuid4())).id
    compiled = _build_graph(repo, llm)

    start_case(
        compiled,
        AgentState(
            conversation_graph=ConversationGraphState(case_id=case_id),
            current_message=_message("Wanted Finance looped in before this ships."),
        ),
    )
    assert repo.get_by_id(case_id).attempt_count == 1
    decisions_before = len(repo.decisions)

    # Dana (already present, not a required role) replies — nothing about missing_roles
    # changes, so this can't resolve; attempt_count(1) already meets payment_system's
    # escalate_after_attempts(1), so this must escalate regardless of cooldown.
    reply = InboundMessage(
        channel=Channel.EMAIL,
        sender=MessageParticipant(name="Dana Kapoor", email="dana@co.com", role="Engineer"),
        body="Just a heads up, still in progress.",
        received_at=datetime.now(UTC),
    )
    result = resume_case(compiled, case_id, reply)

    assert "__interrupt__" in result
    case = repo.get_by_id(case_id)
    assert case.priority == Priority.HIGH  # was already HIGH; escalate keeps it HIGH
    assert case.attempt_count == 2  # escalate still sends, through the same chain

    new_nodes = [d.node_name for d in repo.decisions[decisions_before:]]
    assert "escalate" in new_nodes
    evaluator_decision = next(
        d for d in repo.decisions[decisions_before:] if d.node_name == "resolution_evaluator"
    )
    assert evaluator_decision.chosen_action["outcome"] == "escalate"
    escalate_decision = next(
        d for d in repo.decisions[decisions_before:] if d.node_name == "escalate"
    )
    assert escalate_decision.chosen_action["escalate_to_roles"] == ["Security", "Finance"]


def test_single_invoke_call_never_runs_unboundedly() -> None:
    """Structural "no infinite loop" guarantee: every path out of resolution_evaluator either
    hits wait_for_reply (which interrupts immediately) or resolve_case (-> END) — so one
    `invoke()` call is always bounded to one pass through REASONING_SEQUENCE, optionally
    escalate, and optionally SEND_SEQUENCE. Runs several forced-escalation resumes in a row
    and confirms each stays within that bound and none raises (e.g. LangGraph's own
    recursion-limit safety net never trips).
    """
    repo = FakeCaseRepository()
    llm = FakeLLMPort()
    case_id = repo.add(Case(id=uuid4())).id
    compiled = _build_graph(repo, llm)

    start_case(
        compiled,
        AgentState(
            conversation_graph=ConversationGraphState(case_id=case_id),
            current_message=_message("Wanted Finance looped in before this ships."),
        ),
    )

    max_nodes_per_pass = len(REASONING_SEQUENCE) + 1 + len(SEND_SEQUENCE)  # +1 for escalate
    for _ in range(4):
        decisions_before = len(repo.decisions)
        reply = InboundMessage(
            channel=Channel.EMAIL,
            sender=MessageParticipant(name="Dana Kapoor", email="dana@co.com", role="Engineer"),
            body="Still working on it.",
            received_at=datetime.now(UTC),
        )
        result = resume_case(compiled, case_id, reply)  # must return, never hang or raise
        assert "__interrupt__" in result
        nodes_this_pass = len(repo.decisions) - decisions_before
        assert nodes_this_pass <= max_nodes_per_pass
