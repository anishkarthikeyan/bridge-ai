"""TelegramAdapter — implements ChannelPort for Telegram. Wire-format translation only, in
both directions — no business logic.

Inbound payload shape (Phase 6.6 correction): the same Caspian-normalized envelope
EmailAdapter already expects, not Telegram's raw Bot API `Update` object as this file
originally assumed. Inspecting the real, now-installed `caspian-sdk` (Phase 6.6 Part
"FIRST: INSPECT CURRENT SDK") shows why: `caspian_sdk.CommClient` delivers every inbound
event — on every channel — as one generic `Message` dataclass (`id`, `conversation_id`,
`sender: dict`, `subject`, `text`, ...); there is no code path through the real SDK's
`on_message`/webhook dispatch that hands an app Telegram's native `Update` shape. Caspian
normalizes across channels; that's the point of a unified comms gateway. The previous
assumption ("Caspian is assumed to pass Telegram events through close to as-received") did
not hold once checked against the real SDK, so this adapter now parses the same shape
`RealCaspianClient` (app/integrations/real_caspian_client.py) produces from a real
`caspian_sdk.Message`:

    {
      "from": {"name": str, "telegram_handle": str | null, "role": null},
      "cc": [],
      "subject": null,
      "body": str,
      "thread_ref": str | null,    # Caspian's own conversation_id
      "message_ref": str | null,   # Caspian's own message id
      "received_at": str | null    # ISO 8601
    }

`role` still has no place in Telegram's own schema — unchanged from the original design note
below, just relocated: an inbound Telegram sender's role, if known, comes from matching their
handle against the Conversation Graph's participants or the role directory, not from the wire
payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.dto.inbound_message import InboundMessage, MessageParticipant
from app.application.ports.channel_port import ChannelPort, SendResult
from app.domain.entities.outbound_action import OutboundAction
from app.domain.value_objects.channel import Channel
from app.integrations.outbound.caspian_gateway import CaspianGateway


class TelegramAdapter(ChannelPort):
    def __init__(self, caspian_gateway: CaspianGateway) -> None:
        self._caspian_gateway = caspian_gateway

    def send(self, action: OutboundAction) -> SendResult:
        payload = self._to_wire_format(action)
        return self._caspian_gateway.send(Channel.TELEGRAM, action.recipient.address, payload)

    def parse_inbound(self, raw: dict) -> InboundMessage:
        sender = self._parse_participant(raw["from"])
        received_at = raw.get("received_at")

        return InboundMessage(
            channel=Channel.TELEGRAM,
            sender=sender,
            subject=raw.get("subject"),
            body=raw["body"],
            external_thread_ref=raw.get("thread_ref"),
            external_message_ref=raw.get("message_ref"),
            received_at=datetime.fromisoformat(received_at) if received_at else None,
        )

    @staticmethod
    def _to_wire_format(action: OutboundAction) -> dict[str, Any]:
        return {"chat_id": action.recipient.address, "text": action.message}

    @staticmethod
    def _parse_participant(raw: dict) -> MessageParticipant:
        return MessageParticipant(
            name=raw["name"], telegram_handle=raw.get("telegram_handle"), role=raw.get("role")
        )
