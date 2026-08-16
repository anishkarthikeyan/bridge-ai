"""Real end-to-end verification (Phase 6.5 Part 16) — real Postgres (both the Case/Decision
tables and the LangGraph checkpoint), the real Featherless API with the configured
DeepSeek-V3.2 model, and the existing Caspian local/test abstraction (LocalCaspianClient —
Part 10: the real caspian-sdk package still isn't available). Nothing about the LLM is faked
here; only the LLM is unpredictable, so this test asserts structural invariants that hold
regardless of exactly which topic/roles the model names, rather than a hardcoded topic.

Demonstrates, all for real:

    inbound message
    -> real Featherless intent extraction, entity extraction, topic classification
    -> deterministic policy load, stakeholder detection, health, priority, resolution
    -> real Featherless message generation
    -> Decision PENDING -> dispatch -> WAIT (a real Postgres checkpoint pause)
    -> scheduler due check (next_check_at forced into the past, exactly like a real 6-hour
       wait would look after the fact) -> EvaluateCaseUseCase follows up with NO new message
    -> a real reply (or two) closing every remaining required role
    -> RESOLVED -> END

Skips cleanly (Part 6) if either Postgres or FEATHERLESS_API_KEY isn't available, rather than
failing unrelated tests. Uses exactly one inbound message, one scheduler tick, and as few
replies as the classified topic actually requires — never "hundreds" of live calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.application.dto.inbound_message import InboundMessage, MessageParticipant
from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.application.use_cases.evaluate_case import EvaluateCaseUseCase
from app.application.use_cases.ingest_inbound_message import IngestInboundMessageUseCase
from app.application.use_cases.run_followup_sweep import RunFollowupSweepUseCase
from app.brain.checkpointer import postgres_checkpointer
from app.brain.graph import build_graph
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.policy_loader import PolicyLoader
from app.domain.services.role_directory_loader import RoleDirectoryLoader
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.resolution_state import ResolutionState
from app.infrastructure.config import get_settings
from app.infrastructure.db import SessionLocal
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.inbound.caspian_handler import BridgeAgentHandler
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.llm.featherless_client import FeatherlessClient
from app.integrations.outbound.caspian_gateway import CaspianGateway
from app.integrations.persistence.sqlalchemy.repositories.case_repository import (
    SqlAlchemyCaseRepository,
)

# A known candidate, by role, for every required role any topic in policies/software.yaml can
# name (policies/role_directory.yaml) — used to reply as whichever role is still missing,
# without hardcoding which topic the live model actually classifies this message as.
_CANDIDATE_BY_ROLE = {
    "Security": ("John Ortiz", "john@co.com"),
    "QA": ("Priya Rao", "priya.rao@co.com"),
    "Product": ("Sofia Alvarez", "sofia@co.com"),
    "DBA": ("Wei Zhang", "wei@co.com"),
    "DevOps": ("Elena Voss", "elena@co.com"),
    "Finance": ("Priya Sundaram", "priya@co.com"),
    "Support": ("Sam Okafor", "sam@co.com"),
}

_THREAD_REF = f"e2e-thread-{uuid4().hex[:8]}"


def _database_reachable() -> bool:
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


pytestmark = [
    pytest.mark.skipif(
        not _database_reachable(), reason="Postgres not reachable — skipping real end-to-end test"
    ),
    pytest.mark.skipif(
        not get_settings().featherless_api_key,
        reason="FEATHERLESS_API_KEY not configured — skipping real end-to-end test",
    ),
]


def test_real_inbound_message_drives_the_full_autonomous_lifecycle() -> None:
    settings = get_settings()
    role_directory = RoleDirectoryLoader().load("policies/role_directory.yaml")
    channel_registry = ChannelRegistry(available_channels={Channel.EMAIL, Channel.TELEGRAM})
    role_resolver = RoleResolver(channel_registry)
    caspian_client = LocalCaspianClient()
    gateway = CaspianGateway(caspian_client)
    adapter_registry = ChannelAdapterRegistry(
        {Channel.EMAIL: EmailAdapter(gateway), Channel.TELEGRAM: TelegramAdapter(gateway)}
    )
    llm_client = FeatherlessClient(settings)

    with postgres_checkpointer(settings.database_url) as checkpointer, SessionLocal() as session:
        case_repository = SqlAlchemyCaseRepository(session)
        dispatch_use_case = DispatchMessageUseCase(case_repository, adapter_registry)
        compiled_graph = build_graph(
            case_repository,
            llm_client,
            adapter_registry,
            channel_registry=channel_registry,
            role_resolver=role_resolver,
            role_directory=role_directory,
            dispatch_use_case=dispatch_use_case,
        ).compile(checkpointer=checkpointer)

        inbound_router = IngestInboundMessageUseCase(case_repository, compiled_graph)
        handler = BridgeAgentHandler(adapter_registry, inbound_router)
        caspian_client.register_handler(handler)

        case_id = None
        try:
            # 1) Real inbound message -> real LLM extraction/classification -> deterministic
            #    reasoning -> real LLM message generation -> dispatch -> WAIT.
            caspian_client.simulate_inbound(
                "email",
                {
                    "from": {"name": "Dana Kapoor", "email": "dana@co.com", "role": "Engineer"},
                    "cc": [],
                    "subject": "Changing the refund flow to settle same-day",
                    "body": (
                        "We're changing refunds to settle same-day instead of the current "
                        "3-day hold. Wanted Finance looped in before this ships next week."
                    ),
                    "thread_ref": _THREAD_REF,
                    "message_ref": "msg-1",
                },
            )

            case = case_repository.find_by_conversation_ref("email", _THREAD_REF)
            assert case is not None
            case_id = case.id
            session.commit()

            assert isinstance(case.topic, str) and case.topic  # a real classification happened
            assert case.attempt_count == 1  # a real message was really dispatched
            assert case.resolution_status == ResolutionState.OPEN
            assert len(caspian_client.sent) == 1

            classify_decision = next(d for d in case.decisions if d.node_name == "classify_topic")
            assert 0.0 <= classify_decision.confidence <= 1.0
            dispatch_decision = next(d for d in case.decisions if d.node_name == "dispatch")
            assert dispatch_decision.status.value == "success"

            # 2) Force this case's cooldown to have already expired — what a real multi-hour
            #    wait would look like after the fact (same technique already proven in
            #    tests/integration/test_brain_graph.py) — then let the scheduler's own use
            #    cases (not the graph directly) discover and act on it with NO new message.
            thread_config = {"configurable": {"thread_id": str(case_id)}}
            checkpointed_graph = compiled_graph.get_state(thread_config).values[
                "conversation_graph"
            ]
            from dataclasses import replace

            compiled_graph.update_state(
                thread_config,
                {
                    "conversation_graph": replace(
                        checkpointed_graph, next_check_at=datetime.now(UTC) - timedelta(hours=1)
                    )
                },
            )
            case_repository.save(
                replace(case, next_check_at=datetime.now(UTC) - timedelta(hours=1))
            )
            session.commit()

            evaluate_case_use_case = EvaluateCaseUseCase(
                case_repository,
                llm_client,
                dispatch_use_case,
                policy_loader=PolicyLoader(),
                channel_registry=channel_registry,
                role_resolver=role_resolver,
                role_directory=role_directory,
                compiled_graph=compiled_graph,
            )
            sweep_results = RunFollowupSweepUseCase(case_repository, evaluate_case_use_case).run()
            session.commit()

            due_result = next((r for r in sweep_results if r.case_id == case_id), None)
            assert due_result is not None, "the scheduler did not pick up the due case"
            assert due_result.error is None

            case = case_repository.get_by_id(case_id)
            assert case.attempt_count == 2 or case.resolution_status == ResolutionState.RESOLVED
            if case.resolution_status != ResolutionState.RESOLVED:
                assert len(caspian_client.sent) == 2  # a second real message, no reply needed

            # 3) Reply as whichever roles are still missing (whatever the live model actually
            #    classified this case's topic as) until every required role is satisfied.
            for role in list(case.missing_roles):
                if case.resolution_status == ResolutionState.RESOLVED:
                    break
                name, email = _CANDIDATE_BY_ROLE.get(role, ("Alex Reviewer", "alex@co.com"))
                reply = InboundMessage(
                    channel=Channel.EMAIL,
                    sender=MessageParticipant(name=name, email=email, role=role),
                    body="Approved from my side — looks good.",
                    external_thread_ref=_THREAD_REF,
                    received_at=datetime.now(UTC),
                )
                inbound_router.handle(reply)
                session.commit()
                case = case_repository.get_by_id(case_id)

            case = case_repository.get_by_id(case_id)
            assert case.resolution_status == ResolutionState.RESOLVED
            assert case.missing_roles == []
            resolve_decision = next(d for d in case.decisions if d.node_name == "resolve_case")
            assert resolve_decision.chosen_action["resolution_status"] == "resolved"
        finally:
            # Cleanup: this test writes real rows (Case aggregate + LangGraph checkpoint) —
            # remove them so repeated runs don't accumulate demo data.
            session.rollback()
            if case_id is not None:
                session.execute(text("DELETE FROM cases WHERE id = :id"), {"id": str(case_id)})
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    session.execute(
                        text(f"DELETE FROM {table} WHERE thread_id = :id"), {"id": str(case_id)}
                    )
                session.commit()
