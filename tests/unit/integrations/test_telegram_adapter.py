"""TelegramAdapter unit tests (Phase 6.6) — proves it now parses the Caspian-normalized
envelope (the shape RealCaspianClient actually produces from a real caspian_sdk.Message),
not Telegram's raw Bot API `Update` object as originally assumed. See telegram_adapter.py's
module docstring for why that assumption didn't hold once the real SDK was inspected.
"""

from __future__ import annotations

from app.domain.value_objects.channel import Channel
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.outbound.caspian_gateway import CaspianGateway


def _adapter() -> TelegramAdapter:
    return TelegramAdapter(CaspianGateway(LocalCaspianClient()))


def test_parses_the_caspian_normalized_envelope() -> None:
    raw = {
        "from": {"name": "Alice Chen", "telegram_handle": "@alice_sec", "role": None},
        "cc": [],
        "subject": None,
        "body": "Approved from my side.",
        "thread_ref": "conv-123",
        "message_ref": "msg-456",
    }

    message = _adapter().parse_inbound(raw)

    assert message.channel == Channel.TELEGRAM
    assert message.sender.name == "Alice Chen"
    assert message.sender.telegram_handle == "@alice_sec"
    assert message.sender.role is None
    assert message.body == "Approved from my side."
    assert message.external_thread_ref == "conv-123"
    assert message.external_message_ref == "msg-456"


def test_parses_received_at_when_present() -> None:
    raw = {
        "from": {"name": "Alice", "telegram_handle": "@alice"},
        "body": "hi",
        "thread_ref": "conv-1",
        "message_ref": "msg-1",
        "received_at": "2026-08-15T10:00:00+00:00",
    }

    message = _adapter().parse_inbound(raw)

    assert message.received_at is not None
    assert message.received_at.year == 2026


def test_outbound_wire_format_uses_chat_id_and_text() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.domain.entities.outbound_action import OutboundAction, Recipient
    from app.domain.value_objects.priority import Priority

    action = OutboundAction(
        recipient=Recipient(name="Alice", address="@alice"),
        channel=Channel.TELEGRAM,
        message="Please confirm.",
        priority=Priority.HIGH,
        follow_up_at=datetime.now(UTC),
        decision_id=uuid4(),
        case_id=uuid4(),
    )

    wire = TelegramAdapter._to_wire_format(action)

    assert wire == {"chat_id": "@alice", "text": "Please confirm."}
