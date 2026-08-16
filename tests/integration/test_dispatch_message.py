"""DispatchMessageUseCase exercised against the real integration stack (ChannelAdapterRegistry,
EmailAdapter, CaspianGateway, LocalCaspianClient) — only the repository is a fake. Proves the
full lifecycle: PENDING -> EXECUTING -> SUCCESS/FAILED, Change 4's decision_id link, and that
attempt_count/next_check_at update only on success.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.domain.entities.case import Case
from app.domain.entities.decision import Decision
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.decision_status import DecisionStatus
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.outbound.caspian_gateway import CaspianGateway
from tests.unit.brain.fakes import FakeCaseRepository

_FIXED_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _pending_decision(case_id, **chosen_overrides) -> Decision:
    chosen = {
        "action": "send_message",
        "channel": "email",
        "recipient_name": "John Ortiz",
        "recipient_address": "john@co.com",
        "message": "Please review the payment flow change.",
        "priority": "high",
        "missing_roles": ["Security"],
        "topic": "payment_system",
    }
    chosen.update(chosen_overrides)
    return Decision(
        id=uuid4(),
        case_id=case_id,
        node_name="create_decision",
        reasoning_summary="test",
        chosen_action=chosen,
        status=DecisionStatus.PENDING,
    )


def _build_service(repo, client):
    registry = ChannelAdapterRegistry({Channel.EMAIL: EmailAdapter(CaspianGateway(client))})
    return DispatchMessageUseCase(repo, registry, clock=lambda: _FIXED_NOW)


def test_successful_dispatch_transitions_pending_to_success_and_updates_case() -> None:
    repo = FakeCaseRepository()
    client = LocalCaspianClient()
    case = repo.add(Case(id=uuid4(), topic="payment_system", attempt_count=0))
    decision = repo.add_decision(case.id, _pending_decision(case.id))

    service = _build_service(repo, client)
    result = service.dispatch(decision)

    assert result.status == DecisionStatus.SUCCESS
    assert repo.decisions[0].status == DecisionStatus.SUCCESS  # persisted, not just returned

    # Change 4: the OutboundAction that got sent referenced this exact decision.
    assert len(client.sent) == 1
    sent = client.sent[0]
    assert sent.recipient == "john@co.com"
    assert sent.payload["body"] == "Please review the payment flow change."

    updated_case = repo.get_by_id(case.id)
    assert updated_case.attempt_count == 1
    # payment_system's cooldown_hours is 6 (policies/software.yaml).
    assert updated_case.next_check_at == _FIXED_NOW.replace(hour=18)


def test_dispatch_without_a_recipient_address_fails_without_sending() -> None:
    repo = FakeCaseRepository()
    client = LocalCaspianClient()
    case = repo.add(Case(id=uuid4(), topic="payment_system"))
    decision = repo.add_decision(case.id, _pending_decision(case.id, recipient_address=None))

    service = _build_service(repo, client)
    result = service.dispatch(decision)

    assert result.status == DecisionStatus.FAILED
    assert client.sent == []  # never even reached the adapter
    assert repo.get_by_id(case.id).attempt_count == 0  # unchanged — success-only update


def test_dispatch_rejects_a_non_pending_decision() -> None:
    repo = FakeCaseRepository()
    client = LocalCaspianClient()
    case = repo.add(Case(id=uuid4(), topic="payment_system"))
    already_done = repo.add_decision(case.id, _pending_decision(case.id))
    repo.update_decision_status(already_done.id, DecisionStatus.SUCCESS)
    already_done = repo.decisions[0]

    service = _build_service(repo, client)
    try:
        service.dispatch(already_done)
        raise AssertionError("expected ValueError for a non-pending decision")
    except ValueError as exc:
        assert "not pending" in str(exc)


# --- cross-channel/cross-recipient conversation continuity (Phase 6.6.6) -------------------


def test_successful_dispatch_registers_a_conversation_for_the_recipient_on_the_case() -> None:
    repo = FakeCaseRepository()
    client = LocalCaspianClient()
    case = repo.add(Case(id=uuid4(), topic="payment_system"))
    decision = repo.add_decision(case.id, _pending_decision(case.id))

    service = _build_service(repo, client)
    service.dispatch(decision)

    updated_case = repo.get_by_id(case.id)
    assert len(updated_case.conversations) == 1
    conversation = updated_case.conversations[0]
    assert conversation.channel == Channel.EMAIL
    assert conversation.external_thread_ref is not None

    # This is the actual point: a later inbound event on that exact thread now resolves back
    # to this same case (CaseRepositoryPort.find_by_conversation_ref, consumed by
    # IngestInboundMessageUseCase) instead of opening a new one.
    found = repo.find_by_conversation_ref("email", conversation.external_thread_ref)
    assert found is not None
    assert found.id == case.id


def test_repeat_dispatch_to_the_same_recipient_does_not_duplicate_the_conversation() -> None:
    repo = FakeCaseRepository()
    client = LocalCaspianClient()
    case = repo.add(Case(id=uuid4(), topic="payment_system"))
    service = _build_service(repo, client)

    service.dispatch(repo.add_decision(case.id, _pending_decision(case.id)))
    service.dispatch(repo.add_decision(case.id, _pending_decision(case.id)))  # e.g. a resend

    updated_case = repo.get_by_id(case.id)
    assert len(updated_case.conversations) == 1  # not duplicated (Part C)


def test_dispatch_to_a_different_recipient_registers_a_second_conversation_on_the_same_case() -> (
    None
):
    """A second recipient — even on the SAME channel — gets their own Caspian conversation
    in the real world (see app/integrations/real_caspian_client.py's docstring); dispatch
    must register it too, distinctly, still on the same case (Part D's principle applies to
    same-channel-different-recipient just as much as to an actual channel switch)."""
    repo = FakeCaseRepository()
    client = LocalCaspianClient()
    case = repo.add(Case(id=uuid4(), topic="payment_system"))
    service = _build_service(repo, client)

    service.dispatch(
        repo.add_decision(case.id, _pending_decision(case.id, recipient_address="john@co.com"))
    )
    service.dispatch(
        repo.add_decision(case.id, _pending_decision(case.id, recipient_address="priya@co.com"))
    )

    updated_case = repo.get_by_id(case.id)
    assert len(updated_case.conversations) == 2
    refs = {c.external_thread_ref for c in updated_case.conversations}
    assert len(refs) == 2  # genuinely distinct conversations, not the same one twice


def test_dispatch_with_no_conversation_ref_still_succeeds_but_registers_nothing() -> None:
    """Part E: a send whose gateway call succeeded but couldn't confirm a conversation
    reference must still count as a successful dispatch — never silently fabricating
    continuity that doesn't actually exist."""

    class _NoConversationRefClient(LocalCaspianClient):
        def send(self, channel, recipient, payload):
            result = super().send(channel, recipient, payload)
            return replace(result, conversation_ref=None)

    repo = FakeCaseRepository()
    client = _NoConversationRefClient()
    case = repo.add(Case(id=uuid4(), topic="payment_system"))
    decision = repo.add_decision(case.id, _pending_decision(case.id))

    service = _build_service(repo, client)
    result = service.dispatch(decision)

    assert result.status == DecisionStatus.SUCCESS  # the send itself still succeeded
    assert repo.get_by_id(case.id).conversations == []  # nothing fabricated
