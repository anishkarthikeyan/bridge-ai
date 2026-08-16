"""Tests for the autonomous follow-up path (Phase 6.5 Part 8): RunFollowupSweepUseCase +
EvaluateCaseUseCase discovering and progressing a case with NO new inbound message — the
scenario called out explicitly: "a case waiting for a reply must be able to progress even if
nobody replies." Real dispatch, real RoleResolver/ChannelRegistry/ResolutionEvaluator — only
the LLM (FakeLLMPort) and the Caspian client (LocalCaspianClient) are non-production stand-ins.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.application.use_cases.evaluate_case import EvaluateCaseUseCase
from app.application.use_cases.run_followup_sweep import RunFollowupSweepUseCase
from app.domain.entities.case import Case
from app.domain.entities.participant import Participant
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.role_directory_loader import RoleDirectoryLoader
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.communication_health import CommunicationHealth
from app.domain.value_objects.participant_source import ParticipantSource
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_outcome import ResolutionOutcome
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.outbound.caspian_gateway import CaspianGateway
from tests.unit.brain.fakes import FakeCaseRepository, FakeLLMPort

_FIXED_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_ROLE_DIRECTORY = RoleDirectoryLoader().load("policies/role_directory.yaml")


def _stack(repo: FakeCaseRepository):
    caspian_client = LocalCaspianClient()
    gateway = CaspianGateway(caspian_client)
    registry = ChannelAdapterRegistry(
        {Channel.EMAIL: EmailAdapter(gateway), Channel.TELEGRAM: TelegramAdapter(gateway)}
    )
    channel_registry = ChannelRegistry(available_channels={Channel.EMAIL, Channel.TELEGRAM})
    role_resolver = RoleResolver(channel_registry)
    dispatch_use_case = DispatchMessageUseCase(repo, registry, clock=lambda: _FIXED_NOW)
    evaluate_case_use_case = EvaluateCaseUseCase(
        repo,
        FakeLLMPort(topic="database_migration"),
        dispatch_use_case,
        channel_registry=channel_registry,
        role_resolver=role_resolver,
        role_directory=_ROLE_DIRECTORY,
        clock=lambda: _FIXED_NOW,
    )
    return caspian_client, evaluate_case_use_case


def _due_case(repo: FakeCaseRepository, *, next_check_at: datetime) -> Case:
    """database_migration: required=[DBA, DevOps, QA], escalate_after_attempts=2,
    cooldown_hours=8, max_attempts=5 (policies/software.yaml) — DBA and DevOps already
    present, QA missing, one prior attempt already made."""
    case = repo.add(
        Case(
            id=uuid4(),
            topic="database_migration",
            required_roles=["DBA", "DevOps", "QA"],
            missing_roles=["QA"],
            communication_health=CommunicationHealth.AT_RISK,
            priority=Priority.HIGH,
            attempt_count=1,
            next_check_at=next_check_at,
        )
    )
    repo.add_participant(
        case.id,
        Participant(
            id=uuid4(),
            case_id=case.id,
            name="Wei Zhang",
            role="DBA",
            email="wei@co.com",
            source=ParticipantSource.EXPLICIT,
        ),
    )
    repo.add_participant(
        case.id,
        Participant(
            id=uuid4(),
            case_id=case.id,
            name="Elena Voss",
            role="DevOps",
            email="elena@co.com",
            source=ParticipantSource.EXPLICIT,
        ),
    )
    return repo.get_by_id(case.id)


def test_sweep_discovers_and_follows_up_a_due_case_with_no_new_message() -> None:
    repo = FakeCaseRepository()
    _due_case(repo, next_check_at=_FIXED_NOW - timedelta(hours=1))
    caspian_client, evaluate_case_use_case = _stack(repo)

    sweep = RunFollowupSweepUseCase(repo, evaluate_case_use_case, clock=lambda: _FIXED_NOW)
    results = sweep.run()

    assert len(results) == 1
    assert results[0].outcome == ResolutionOutcome.FOLLOW_UP
    case = repo.get_by_id(results[0].case_id)
    assert case.attempt_count == 2  # a real follow-up was dispatched, no reply needed
    assert case.next_check_at == _FIXED_NOW + timedelta(hours=8)  # database_migration cooldown
    assert len(caspian_client.sent) == 1

    decision_nodes = [d.node_name for d in repo.decisions]
    assert "receive_message" not in decision_nodes  # no message was processed
    assert "extract_intent" not in decision_nodes  # no LLM calls for tasks that need a message
    assert "dispatch" in decision_nodes


def test_sweep_respects_next_check_at_and_ignores_a_case_not_yet_due() -> None:
    repo = FakeCaseRepository()
    _due_case(repo, next_check_at=_FIXED_NOW + timedelta(hours=1))  # not due yet
    _caspian_client, evaluate_case_use_case = _stack(repo)

    sweep = RunFollowupSweepUseCase(repo, evaluate_case_use_case, clock=lambda: _FIXED_NOW)
    results = sweep.run()

    assert results == []


def test_sweep_does_not_duplicate_dispatch_across_consecutive_runs() -> None:
    """The next_check_at a successful dispatch advances is what keeps a case from being
    immediately due again — running the sweep twice against the same clock dispatches once."""
    repo = FakeCaseRepository()
    _due_case(repo, next_check_at=_FIXED_NOW - timedelta(hours=1))
    caspian_client, evaluate_case_use_case = _stack(repo)
    sweep = RunFollowupSweepUseCase(repo, evaluate_case_use_case, clock=lambda: _FIXED_NOW)

    first = sweep.run()
    second = sweep.run()

    assert len(first) == 1
    assert second == []  # the case is no longer due
    assert len(caspian_client.sent) == 1


def test_sweep_skips_a_case_already_claimed_by_another_process_or_tick() -> None:
    """Mirrors the real repository's SKIP LOCKED contract (see
    FakeCaseRepository.claimed_case_ids) — Part 8's "do not send the same follow-up twice"
    across concurrent scheduler ticks/processes."""
    repo = FakeCaseRepository()
    case = _due_case(repo, next_check_at=_FIXED_NOW - timedelta(hours=1))
    repo.claimed_case_ids.add(case.id)
    caspian_client, evaluate_case_use_case = _stack(repo)

    sweep = RunFollowupSweepUseCase(repo, evaluate_case_use_case, clock=lambda: _FIXED_NOW)
    results = sweep.run()

    assert results == []
    assert caspian_client.sent == []


def test_a_single_case_failure_does_not_abort_the_rest_of_the_sweep() -> None:
    repo = FakeCaseRepository()
    _due_case(repo, next_check_at=_FIXED_NOW - timedelta(hours=1))
    _due_case(repo, next_check_at=_FIXED_NOW - timedelta(hours=1))
    _caspian_client, evaluate_case_use_case = _stack(repo)

    call_count = 0
    real_evaluate = evaluate_case_use_case.evaluate

    def _flaky_evaluate(case):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated transient failure")
        return real_evaluate(case)

    evaluate_case_use_case.evaluate = _flaky_evaluate  # type: ignore[method-assign]
    sweep = RunFollowupSweepUseCase(repo, evaluate_case_use_case, clock=lambda: _FIXED_NOW)
    results = sweep.run()

    assert len(results) == 2
    assert results[0].outcome is None and results[0].error == "simulated transient failure"
    assert results[1].outcome == ResolutionOutcome.FOLLOW_UP
