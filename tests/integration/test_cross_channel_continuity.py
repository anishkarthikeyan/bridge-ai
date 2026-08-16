"""Cross-channel and same-channel-different-recipient Case continuity (Phase 6.6.6) — proves
the fix end to end through the real production stack (the LangGraph brain,
IngestInboundMessageUseCase, BridgeAgentHandler, DispatchMessageUseCase, CaspianGateway).
Only LocalCaspianClient (not the real caspian-sdk) stands in for the transport here, exactly
like every other Phase 6 test in this suite — the real-SDK conversation-discovery mechanism
itself (`RealCaspianClient._await_conversation_id`) is covered separately in
tests/unit/integrations/test_real_caspian_client.py.

Uses a custom, test-local RoleDirectory (not policies/role_directory.yaml) so the scenario is
deterministic: this directory's "Security" candidate is reachable ONLY via Telegram, which is
what makes escalation naturally dispatch there — RoleResolver, ChannelRegistry,
ChannelSelectionRules, and ResolutionEvaluator are all exercised completely unmodified; only
the fixture data differs from the real policy pack's role directory.
"""

from __future__ import annotations

from types import MappingProxyType

from langgraph.checkpoint.memory import InMemorySaver

from app.application.use_cases.ingest_inbound_message import IngestInboundMessageUseCase
from app.brain.graph import build_graph
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.candidate_contact import CandidateContact
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.resolution_state import ResolutionState
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.inbound.caspian_handler import BridgeAgentHandler
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.outbound.caspian_gateway import CaspianGateway
from tests.unit.brain.fakes import FakeCaseRepository, FakeLLMPort

# payment_system (policies/software.yaml) requires [Finance, Security, Support] and escalates
# (after 1 attempt) to [Security, Finance]. This directory intentionally makes Security
# reachable ONLY via Telegram, so escalation naturally dispatches there.
_ROLE_DIRECTORY = MappingProxyType(
    {
        "Finance": (
            CandidateContact(
                name="Priya Sundaram", role="Finance", email="priya@co.com", preference_rank=1
            ),
        ),
        "Security": (
            CandidateContact(
                name="Tal Cohen",
                role="Security",
                telegram_handle="@tal_security",
                preference_rank=1,
            ),
        ),
        "Support": (
            CandidateContact(
                name="Sam Okafor", role="Support", email="sam@co.com", preference_rank=1
            ),
        ),
    }
)

_EMAIL_EVENT = {
    "from": {"name": "Dana Kapoor", "email": "dana@co.com", "role": "Engineer"},
    "cc": [],
    "subject": "Changing the refund flow to settle same-day",
    "body": "We're changing refunds to settle same-day. Wanted Finance looped in.",
    "thread_ref": "thread-continuity-0001",
    "message_ref": "msg-1",
}


def _build_stack():
    repo = FakeCaseRepository()
    llm = FakeLLMPort()  # default topic: payment_system (escalate_after_attempts=1)
    caspian_client = LocalCaspianClient()
    gateway = CaspianGateway(caspian_client)
    registry = ChannelAdapterRegistry(
        {Channel.EMAIL: EmailAdapter(gateway), Channel.TELEGRAM: TelegramAdapter(gateway)}
    )
    channel_registry = ChannelRegistry(available_channels={Channel.EMAIL, Channel.TELEGRAM})
    role_resolver = RoleResolver(channel_registry)

    compiled_graph = build_graph(
        repo,
        llm,
        registry,
        channel_registry=channel_registry,
        role_resolver=role_resolver,
        role_directory=_ROLE_DIRECTORY,
    ).compile(checkpointer=InMemorySaver())

    inbound_router = IngestInboundMessageUseCase(repo, compiled_graph)
    handler = BridgeAgentHandler(registry, inbound_router)
    caspian_client.register_handler(handler)  # THE one handler

    return repo, caspian_client


def _reply(name: str, email: str, role: str, body: str, message_ref: str, thread_ref: str) -> dict:
    return {
        "from": {"name": name, "email": email, "role": role},
        "cc": [],
        "subject": "Re: Changing the refund flow to settle same-day",
        "body": body,
        "thread_ref": thread_ref,
        "message_ref": message_ref,
    }


# --- Test 1: same-channel, different recipient -----------------------------------------------


def test_same_channel_different_recipient_conversation_registered_and_reply_resumes_case() -> None:
    """Existing Email Case -> Email outbound (to a recipient who isn't the original sender)
    -> conversation registered/reused correctly -> reply resolves to same Case."""
    repo, caspian_client = _build_stack()
    caspian_client.simulate_inbound("email", _EMAIL_EVENT)

    case_id = next(iter(repo.cases.keys()))
    case = repo.get_by_id(case_id)
    assert case.attempt_count == 1  # dispatched to Finance (Priya) over email

    email_conversations = [c for c in case.conversations if c.channel == Channel.EMAIL]
    # One from the inbound thread (ReceiveMessageNode), one from dispatching to Priya — a
    # distinct Caspian conversation in the real world even though it's the same channel (see
    # app/integrations/real_caspian_client.py's docstring).
    assert len(email_conversations) == 2
    outbound_thread_ref = next(
        c.external_thread_ref
        for c in email_conversations
        if c.external_thread_ref != "thread-continuity-0001"
    )

    caspian_client.simulate_inbound(
        "email",
        _reply(
            "Priya Sundaram",
            "priya@co.com",
            "Finance",
            "Looks fine from Finance's side.",
            "msg-priya-1",
            outbound_thread_ref,
        ),
    )

    assert len(repo.cases) == 1  # no new case
    assert case_id in repo.cases
    resumed_case = repo.get_by_id(case_id)
    assert any(p.name == "Priya Sundaram" for p in resumed_case.participants)


# --- Test 2/3: cross-channel escalation --------------------------------------------------------


def test_cross_channel_escalation_registers_telegram_conversation_on_same_case() -> None:
    """Existing Email Case -> Telegram outbound (escalation) -> Telegram Conversation
    registered under the SAME Case."""
    repo, caspian_client = _build_stack()
    caspian_client.simulate_inbound("email", _EMAIL_EVENT)
    case_id = next(iter(repo.cases.keys()))
    assert repo.get_by_id(case_id).attempt_count == 1

    # payment_system's escalate_after_attempts=1 — attempt_count already meets it, so any
    # reply now triggers ESCALATE, which (this directory) resolves Security via Telegram.
    caspian_client.simulate_inbound(
        "email",
        _reply(
            "Dana Kapoor",
            "dana@co.com",
            "Engineer",
            "Still waiting on sign-off.",
            "msg-2",
            "thread-continuity-0001",
        ),
    )

    case = repo.get_by_id(case_id)
    assert case.attempt_count == 2  # the escalation itself dispatched
    assert [d for d in repo.decisions if d.node_name == "escalate"]  # escalation really happened

    create_decision = [d for d in repo.decisions if d.node_name == "create_decision"][-1]
    assert create_decision.chosen_action["channel"] == "telegram"
    assert create_decision.chosen_action["recipient_name"] == "Tal Cohen"

    telegram_conversations = [c for c in case.conversations if c.channel == Channel.TELEGRAM]
    assert len(telegram_conversations) == 1
    assert telegram_conversations[0].external_thread_ref is not None


def test_cross_channel_telegram_reply_resumes_the_same_case_and_does_not_duplicate() -> None:
    """Telegram inbound using the registered conversation reference ->
    IngestInboundMessageUseCase finds the SAME Case (Part D); a second Case is never created
    (Part 3's explicit requirement)."""
    repo, caspian_client = _build_stack()
    caspian_client.simulate_inbound("email", _EMAIL_EVENT)
    case_id = next(iter(repo.cases.keys()))
    caspian_client.simulate_inbound(
        "email",
        _reply(
            "Dana Kapoor",
            "dana@co.com",
            "Engineer",
            "Still waiting on sign-off.",
            "msg-2",
            "thread-continuity-0001",
        ),
    )
    case = repo.get_by_id(case_id)
    telegram_conversation = next(c for c in case.conversations if c.channel == Channel.TELEGRAM)
    cases_before = len(repo.cases)
    decisions_before = len(repo.decisions)

    caspian_client.simulate_inbound(
        "telegram",
        {
            "from": {"name": "Tal Cohen", "telegram_handle": "@tal_security", "role": "Security"},
            "body": "Approved from my side.",
            "thread_ref": telegram_conversation.external_thread_ref,
            "message_ref": "msg-tal-1",
        },
    )

    # Part 3: no duplicate Case.
    assert len(repo.cases) == cases_before
    assert case_id in repo.cases

    resumed_case = repo.get_by_id(case_id)
    assert len(repo.decisions) > decisions_before  # reasoning genuinely resumed
    assert any(p.name == "Tal Cohen" for p in resumed_case.participants)  # the reply was folded
    # into the case's real participant list (detect_missing_stakeholders saw it — payment_system's
    # escalate_after_attempts=1 keeps re-escalating regardless, per EscalateNode's documented
    # "repurposes missing_roles for targeting" behavior, so missing_roles itself isn't a
    # reliable post-escalate signal here; participants is the direct, unambiguous one).
    # Every persisted decision, before and after, still belongs to the ONE original case —
    # proof the telegram reply was folded into it, not tracked against a second one.
    assert {d.case_id for d in repo.decisions} == {case_id}


# --- capstone: the full diagrammed flow, all the way to RESOLVED ------------------------------


def test_full_cross_channel_flow_email_inbound_to_telegram_escalation_to_resolved() -> None:
    """The complete flow from the task's own diagram: Email inbound -> Bridge AI reasoning ->
    Telegram outbound (escalation) -> Telegram reply -> same Case -> reasoning resumes ->
    (closing the two remaining gaps) -> RESOLVED. One Case throughout; one handler throughout."""
    repo, caspian_client = _build_stack()

    caspian_client.simulate_inbound("email", _EMAIL_EVENT)
    case_id = next(iter(repo.cases.keys()))

    caspian_client.simulate_inbound(
        "email",
        _reply(
            "Dana Kapoor",
            "dana@co.com",
            "Engineer",
            "Still waiting.",
            "msg-2",
            "thread-continuity-0001",
        ),
    )
    telegram_ref = next(
        c.external_thread_ref
        for c in repo.get_by_id(case_id).conversations
        if c.channel == Channel.TELEGRAM
    )

    caspian_client.simulate_inbound(
        "telegram",
        {
            "from": {"name": "Tal Cohen", "telegram_handle": "@tal_security", "role": "Security"},
            "body": "Approved from my side.",
            "thread_ref": telegram_ref,
            "message_ref": "msg-tal-1",
        },
    )
    # payment_system's escalate_to_roles is [Security, Finance] — Support is never a
    # proactive escalation target, and escalate_after_attempts=1 means every pass from here
    # keeps re-escalating (EscalateNode's documented "repurposes missing_roles for
    # targeting" behavior — see its own module docstring), so intermediate missing_roles
    # values aren't a stable thing to assert on. What matters, and IS stable: closing every
    # gap eventually resolves the case regardless — Finance replies on the conversation
    # dispatch already registered for her (pass 1), Support replies on the case's original
    # thread (a second person replying on the same email thread is completely realistic).
    email_conversations = [
        c for c in repo.get_by_id(case_id).conversations if c.channel == Channel.EMAIL
    ]
    finance_ref = next(
        c.external_thread_ref
        for c in email_conversations
        if c.external_thread_ref not in ("thread-continuity-0001", telegram_ref)
    )
    caspian_client.simulate_inbound(
        "email",
        _reply(
            "Priya Sundaram", "priya@co.com", "Finance", "Approved.", "msg-priya-1", finance_ref
        ),
    )

    caspian_client.simulate_inbound(
        "email",
        _reply(
            "Sam Okafor",
            "sam@co.com",
            "Support",
            "Confirmed.",
            "msg-sam-1",
            "thread-continuity-0001",
        ),
    )

    final_case = repo.get_by_id(case_id)
    assert final_case.missing_roles == []
    assert final_case.resolution_status == ResolutionState.RESOLVED
    assert len(repo.cases) == 1  # one Case, one handler, the entire way through
    assert {d.case_id for d in repo.decisions} == {case_id}
    assert {p.name for p in final_case.participants} == {
        "Dana Kapoor",
        "Tal Cohen",
        "Priya Sundaram",
        "Sam Okafor",
    }
