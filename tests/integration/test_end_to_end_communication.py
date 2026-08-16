"""The complete autonomous loop, Phase 6's actual objective: a simulated Caspian inbound
email drives the brain all the way through real dispatch (no manual dispatch call needed
anymore — `dispatch` is a graph node now) and pauses; a reply that doesn't yet satisfy every
required role leaves the case correctly WAITing rather than re-sending; a reply that closes
the last gap drives the graph to RESOLVED and a real, verifiable termination — no interrupt,
no further pause, the graph is simply done.

Only the checkpointer (InMemorySaver) and the LLM (FakeLLMPort) are non-production stand-ins
— every other component here, including dispatch, is the real integration code.
"""

from datetime import UTC, datetime

from langgraph.checkpoint.memory import InMemorySaver

from app.application.dto.inbound_message import InboundMessage, MessageParticipant
from app.application.use_cases.ingest_inbound_message import IngestInboundMessageUseCase
from app.brain.graph import build_graph
from app.brain.runner import resume_case
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.role_directory_loader import RoleDirectoryLoader
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.resolution_state import ResolutionState
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.inbound.caspian_handler import BridgeAgentHandler
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.outbound.caspian_gateway import CaspianGateway
from tests.unit.brain.fakes import FakeCaseRepository, FakeLLMPort

_EMAIL_EVENT = {
    "from": {"name": "Dana Kapoor", "email": "dana@co.com", "role": "Engineer"},
    "cc": [{"name": "Priya Sundaram", "email": "priya@co.com", "role": "Finance"}],
    "subject": "Changing the refund flow to settle same-day",
    "body": "We're changing refunds to settle same-day. Wanted Finance looped in.",
    "thread_ref": "thread-pay-0482",
    "message_ref": "msg-1",
}


def _build_stack():
    repo = FakeCaseRepository()
    llm = FakeLLMPort()
    caspian_client = LocalCaspianClient()
    gateway = CaspianGateway(caspian_client)
    registry = ChannelAdapterRegistry(
        {Channel.EMAIL: EmailAdapter(gateway), Channel.TELEGRAM: TelegramAdapter(gateway)}
    )
    channel_registry = ChannelRegistry(available_channels={Channel.EMAIL, Channel.TELEGRAM})
    role_directory = RoleDirectoryLoader().load("policies/role_directory.yaml")
    role_resolver = RoleResolver(channel_registry)

    compiled_graph = build_graph(
        repo,
        llm,
        registry,
        channel_registry=channel_registry,
        role_resolver=role_resolver,
        role_directory=role_directory,
    ).compile(checkpointer=InMemorySaver())

    inbound_router = IngestInboundMessageUseCase(repo, compiled_graph)
    handler = BridgeAgentHandler(registry, inbound_router)
    caspian_client.register_handler(handler)  # THE one handler, registered once

    return repo, caspian_client, compiled_graph


def _reply_event(name: str, email: str, role: str, body: str, message_ref: str) -> dict:
    return {
        "from": {"name": name, "email": email, "role": role},
        "cc": [],
        "subject": "Re: Changing the refund flow to settle same-day",
        "body": body,
        "thread_ref": "thread-pay-0482",
        "message_ref": message_ref,
    }


def test_inbound_email_drives_the_brain_through_real_dispatch_to_wait() -> None:
    repo, caspian_client, _graph = _build_stack()

    caspian_client.simulate_inbound("email", _EMAIL_EVENT)

    assert len(repo.cases) == 1
    case = next(iter(repo.cases.values()))
    assert case.topic == "payment_system"
    assert case.missing_roles == ["Security", "Support"]
    assert case.attempt_count == 1  # dispatch is now a graph node — it already ran
    assert case.next_check_at is not None
    assert case.resolution_status != ResolutionState.RESOLVED

    # create_decision's PENDING record, resolved to John Ortiz (Security, preference_rank 1).
    create_decision = next(d for d in repo.decisions if d.node_name == "create_decision")
    assert create_decision.chosen_action["recipient_name"] == "John Ortiz"
    assert create_decision.chosen_action["recipient_address"] == "john@co.com"

    # dispatch's own decision reflects the send actually happened, for real, through Caspian.
    dispatch_decision = next(d for d in repo.decisions if d.node_name == "dispatch")
    assert dispatch_decision.status == DecisionStatus.SUCCESS
    assert len(caspian_client.sent) == 1
    assert caspian_client.sent[0].recipient == "john@co.com"

    # resolution_evaluator ran and chose FOLLOW_UP (a fresh case, nothing resolved yet).
    evaluator_decision = next(d for d in repo.decisions if d.node_name == "resolution_evaluator")
    assert evaluator_decision.chosen_action["outcome"] == "follow_up"


def test_partial_reply_escalates_when_the_topic_escalates_fast() -> None:
    """payment_system's escalate_after_attempts is 1 (policies/software.yaml) — deliberately
    aggressive for a payment topic. So a reply that doesn't close every gap, arriving after
    just the first attempt, correctly triggers ESCALATE, not WAIT: attempt_count(1) already
    meets the threshold. This is the policy working as designed, not a lesser case of WAIT.
    """
    repo, caspian_client, _graph = _build_stack()
    caspian_client.simulate_inbound("email", _EMAIL_EVENT)
    decisions_before = len(repo.decisions)
    sent_before = len(caspian_client.sent)
    case_id = next(iter(repo.cases.keys()))
    repo.conversation_refs[("email", "thread-pay-0482")] = case_id

    # Security replies, but Support is still missing.
    caspian_client.simulate_inbound(
        "email", _reply_event("John Ortiz", "john@co.com", "Security", "Approved.", "msg-2")
    )

    case = repo.get_by_id(case_id)
    assert case.resolution_status != ResolutionState.RESOLVED
    assert case.attempt_count == 2  # escalate still sends — attempt_count advances
    assert len(caspian_client.sent) == sent_before + 1

    new_decisions = [d.node_name for d in repo.decisions[decisions_before:]]
    assert new_decisions[0] == "wait_for_reply"  # the resumed pause, persisted
    assert "receive_message" in new_decisions  # full reprocessing happened
    evaluator_decision = next(
        d for d in repo.decisions[decisions_before:] if d.node_name == "resolution_evaluator"
    )
    assert evaluator_decision.chosen_action["outcome"] == "escalate"
    assert "escalate" in new_decisions
    # Sent, then paused again — wait_for_reply's own decision for *this* pause won't persist
    # until the next resume, so the last persisted decision is dispatch, not wait_for_reply.
    assert new_decisions[-1] == "dispatch"


def test_final_reply_resolves_and_terminates_the_graph() -> None:
    repo, caspian_client, _graph = _build_stack()
    caspian_client.simulate_inbound("email", _EMAIL_EVENT)
    case_id = next(iter(repo.cases.keys()))
    repo.conversation_refs[("email", "thread-pay-0482")] = case_id

    # This reply escalates (see the test above) rather than resolving — Support is still
    # missing — but a second message does go out.
    caspian_client.simulate_inbound(
        "email", _reply_event("John Ortiz", "john@co.com", "Security", "Approved.", "msg-2")
    )
    assert repo.get_by_id(case_id).attempt_count == 2
    decisions_before_final_reply = len(repo.decisions)

    # Support replies too — every required role for payment_system is now present. RESOLVED
    # is checked before ESCALATE in ResolutionEvaluator, so closing the last gap wins even
    # though attempt_count still meets the escalation threshold structurally.
    caspian_client.simulate_inbound(
        "email",
        _reply_event("Sam Okafor", "sam@co.com", "Support", "Confirmed on our end.", "msg-3"),
    )

    case = repo.get_by_id(case_id)
    assert case.missing_roles == []
    assert case.resolution_status == ResolutionState.RESOLVED

    new_decisions = [d.node_name for d in repo.decisions[decisions_before_final_reply:]]
    assert new_decisions[-2] == "resolution_evaluator"
    assert new_decisions[-1] == "resolve_case"  # the graph's only path to END
    # wait_for_reply appears exactly once — the resumed pause from this reply arriving —
    # and never again, meaning the graph terminated instead of pausing a second time.
    assert new_decisions.count("wait_for_reply") == 1
    assert new_decisions[0] == "wait_for_reply"

    resolve_decision = repo.decisions[-1]
    assert resolve_decision.node_name == "resolve_case"
    assert resolve_decision.chosen_action["resolution_status"] == "resolved"

    # Two sends total (initial + one escalation) — resolving via the final reply itself
    # never triggers a third.
    assert len(caspian_client.sent) == 2
    assert case.attempt_count == 2


def test_resume_case_helper_is_directly_usable_without_going_through_caspian() -> None:
    """app/brain/runner.py's resume_case is still independently callable — inbound routing
    isn't the only path to resuming a paused case."""
    repo, caspian_client, graph = _build_stack()
    caspian_client.simulate_inbound("email", _EMAIL_EVENT)
    case_id = next(iter(repo.cases.keys()))

    reply = InboundMessage(
        channel=Channel.EMAIL,
        sender=MessageParticipant(name="John Ortiz", email="john@co.com", role="Security"),
        body="Approved.",
        external_thread_ref="thread-pay-0482",
        received_at=datetime(2026, 8, 9, 9, 0, tzinfo=UTC),
    )
    result = resume_case(graph, case_id, reply)
    assert "__interrupt__" in result  # Support is still missing — pauses again, doesn't resolve
