"""EmailAdapter — implements ChannelPort for email. Wire-format translation only, in both
directions: building the payload Caspian's email channel expects, and parsing the payload
Caspian delivers for an inbound email event. No business logic — it never decides who, when,
or what to send; that's already fixed on the OutboundAction it's given.

Assumed inbound payload shape (Caspian's actual email-event schema isn't available — see
app/integrations/caspian_client.py's docstring for why — this is the reasonable shape this
build parses, matching examples/*.json's "trigger" objects field-for-field):

    {
      "from": {"name": str, "email": str, "role": str | null},
      "cc": [{"name": str, "email": str, "role": str | null}, ...],
      "subject": str | null,
      "body": str,
      "thread_ref": str | null,
      "message_ref": str | null,
      "received_at": str | null   # ISO 8601
    }
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.dto.inbound_message import InboundMessage, MessageParticipant
from app.application.ports.channel_port import ChannelPort, SendResult
from app.domain.entities.outbound_action import OutboundAction
from app.domain.value_objects.channel import Channel
from app.integrations.outbound.caspian_gateway import CaspianGateway


class EmailAdapter(ChannelPort):
    def __init__(self, caspian_gateway: CaspianGateway) -> None:
        self._caspian_gateway = caspian_gateway

    def send(self, action: OutboundAction) -> SendResult:
        payload = self._to_wire_format(action)
        return self._caspian_gateway.send(Channel.EMAIL, action.recipient.address, payload)

    def parse_inbound(self, raw: dict) -> InboundMessage:
        sender = self._parse_participant(raw["from"])
        cc = tuple(self._parse_participant(p) for p in raw.get("cc", []))
        received_at = raw.get("received_at")

        return InboundMessage(
            channel=Channel.EMAIL,
            sender=sender,
            cc=cc,
            subject=raw.get("subject"),
            body=raw["body"],
            external_thread_ref=raw.get("thread_ref"),
            external_message_ref=raw.get("message_ref"),
            received_at=datetime.fromisoformat(received_at) if received_at else None,
        )

    @staticmethod
    def _to_wire_format(action: OutboundAction) -> dict[str, Any]:
        return {
            "to": action.recipient.address,
            "subject": f"Bridge AI — update on your case ({action.priority.value} priority)",
            "body": action.message,
        }

    @staticmethod
    def _parse_participant(raw: dict) -> MessageParticipant:
        return MessageParticipant(name=raw["name"], email=raw.get("email"), role=raw.get("role"))
