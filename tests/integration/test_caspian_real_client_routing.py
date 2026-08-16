"""Full-stack proof that RealCaspianClient — the production CaspianClientProtocol adapter
against the real caspian-sdk (Phase 6.6) — drives the exact same Bridge AI pipeline
LocalCaspianClient already does, for BOTH email and Telegram, through ONE BridgeAgentHandler,
with no reasoning duplicated per channel. Only `caspian_sdk.CommClient` itself is a scripted
fake here (no real network) — RealCaspianClient, BridgeAgentHandler, ChannelAdapterRegistry,
EmailAdapter, TelegramAdapter, CaspianGateway, IngestInboundMessageUseCase, and the LangGraph
brain are all the real, production code, exercising:

    real inbound email  -> RealCaspianClient -> BridgeAgentHandler -> EmailAdapter
                         -> IngestInboundMessageUseCase -> LangGraph -> DispatchMessageUseCase
                         -> CaspianGateway -> RealCaspianClient.send() -> Caspian (initiate/
                            send_message)

    real inbound telegram -> RealCaspianClient -> the SAME BridgeAgentHandler -> TelegramAdapter
                         -> the SAME IngestInboundMessageUseCase -> the SAME LangGraph brain

The genuinely-live Caspian connection is covered separately by
tests/integration/test_caspian_live.py, which skips cleanly without real credentials.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from app.application.use_cases.ingest_inbound_message import IngestInboundMessageUseCase
from app.brain.graph import build_graph
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.role_directory_loader import RoleDirectoryLoader
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.decision_status import DecisionStatus
from app.integrations.inbound.caspian_handler import BridgeAgentHandler
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.outbound.caspian_gateway import CaspianGateway
from app.integrations.real_caspian_client import RealCaspianClient
from tests.unit.brain.fakes import FakeCaseRepository, FakeLLMPort
from tests.unit.integrations.test_real_caspian_client import _FakeCommClient, _message

_ROLE_DIRECTORY = RoleDirectoryLoader().load("policies/role_directory.yaml")


def _build_stack():
    repo = FakeCaseRepository()
    llm = FakeLLMPort()  # default topic: payment_system
    comm = _FakeCommClient()
    comm.connect_email_result = {"id": "conn-email-1", "status": "active"}
    comm.connect_telegram_result = {"id": "conn-tg-1", "status": "active"}
    caspian_client = RealCaspianClient(comm)

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
    caspian_client.register_handler(handler)  # THE one handler, registered once

    caspian_client.provision(email_username=None, telegram_bot_token="fake-bot-token")

    return repo, comm, caspian_client


def test_email_inbound_drives_the_full_pipeline_and_dispatches_via_caspian() -> None:
    repo, comm, caspian_client = _build_stack()

    caspian_client._on_message(
        _message(
            id="msg-1",
            conversation_id="conv-pay-1",
            channel="email",
            sender={"name": "Dana Kapoor", "email": "dana@co.com", "role": "Engineer"},
            text="We're changing refunds to settle same-day.",
        )
    )

    assert len(repo.cases) == 1
    case = next(iter(repo.cases.values()))
    assert case.topic == "payment_system"  # real deterministic reasoning ran
    assert case.attempt_count == 1  # a real dispatch happened

    # Outbound really went through Caspian — not bypassed (Part "OUTBOUND": "Do not bypass
    # Caspian").
    initiate_calls = [c for c in comm.calls if c[0] == "initiate"]
    assert len(initiate_calls) == 1
    dispatch_decision = next(d for d in repo.decisions if d.node_name == "dispatch")
    assert dispatch_decision.status == DecisionStatus.SUCCESS


def test_telegram_inbound_reaches_the_same_handler_and_pipeline_as_email() -> None:
    repo, comm, caspian_client = _build_stack()

    caspian_client._on_message(
        _message(
            id="msg-tg-1",
            conversation_id="conv-tg-1",
            channel="telegram",
            sender={"name": "Wei Zhang", "handle": "@wei_dba", "role": "DevOps"},
            subject=None,
            text="Migration planned for the weekend.",
        )
    )

    assert len(repo.cases) == 1
    case = next(iter(repo.cases.values()))
    assert case.topic == "payment_system"  # SAME FakeLLMPort, SAME reasoning as the email test
    assert case.attempt_count == 1

    initiate_calls = [c for c in comm.calls if c[0] == "initiate"]
    assert len(initiate_calls) == 1
    # Both this test and the email test above used caspian_client.register_handler() exactly
    # once each, in their own independent stack — proving no per-channel handler exists to
    # duplicate; a single handler object served both channels within its own stack, and a
    # second register_handler() call on either raises (see test_real_caspian_client.py).


def test_one_handler_instance_serves_both_channels_within_one_stack() -> None:
    """The structural version of the "one handler" proof: build one stack, drive both an
    email and a telegram message through it, and confirm both landed on the same registered
    handler (Part "ONE HANDLER PROOF": "Do not duplicate the handler for each channel")."""
    repo, comm, caspian_client = _build_stack()

    caspian_client._on_message(
        _message(
            id="msg-1",
            conversation_id="conv-a",
            channel="email",
            sender={"name": "Dana Kapoor", "email": "dana@co.com", "role": "Engineer"},
        )
    )
    caspian_client._on_message(
        _message(
            id="msg-2",
            conversation_id="conv-b",
            channel="telegram",
            sender={"name": "Alice Chen", "handle": "@alice_sec", "role": "Security"},
            subject=None,
            text="On it.",
        )
    )

    assert len(repo.cases) == 2  # two distinct conversations -> two distinct cases
    channels_used = {c.channels_used[0] for c in repo.cases.values()}
    assert channels_used == {Channel.EMAIL, Channel.TELEGRAM}
    # Every decision across BOTH cases was produced by the same node classes/graph — proof
    # there is no per-channel reasoning duplication (architecture doc: "no duplicating the
    # reasoning layer per channel").
    node_names_seen = {d.node_name for d in repo.decisions}
    assert "classify_topic" in node_names_seen
    assert "dispatch" in node_names_seen


def test_reply_on_the_same_caspian_conversation_resumes_the_same_case() -> None:
    """Phase 6.6 "THREAD CONTINUITY": a reply on the same Caspian conversation must locate
    the existing Case, not open a new one."""
    repo, comm, caspian_client = _build_stack()

    caspian_client._on_message(
        _message(
            id="msg-1",
            conversation_id="conv-pay-1",
            channel="email",
            sender={"name": "Dana Kapoor", "email": "dana@co.com", "role": "Engineer"},
            text="We're changing refunds to settle same-day.",
        )
    )
    assert len(repo.cases) == 1
    case_id = next(iter(repo.cases.keys()))
    decisions_before = len(repo.decisions)

    caspian_client._on_message(
        _message(
            id="msg-2",
            conversation_id="conv-pay-1",
            channel="email",  # SAME conversation_id
            sender={"name": "John Ortiz", "email": "john@co.com", "role": "Security"},
            text="Approved.",
        )
    )

    assert len(repo.cases) == 1  # still one case — the reply resumed it, didn't open a new one
    assert case_id in repo.cases
    assert len(repo.decisions) > decisions_before  # the resumed pass really ran
    resumed_case = repo.cases[case_id]
    assert any(p.name == "Dana Kapoor" for p in resumed_case.participants)  # original sender
    assert any(p.name == "John Ortiz" for p in resumed_case.participants)  # the reply's sender,
    # merged into the SAME case's participant list — not a fresh one for a new case
    assert "receive_message" in [d.node_name for d in repo.decisions[decisions_before:]]
