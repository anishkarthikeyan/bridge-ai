"""CaspianGateway — wraps the Caspian client's outbound send() call. Every channel adapter
is constructed with one; it's the only thing that ever transmits, on any channel — adapters
format, this sends. Wraps CaspianClientProtocol (app/integrations/caspian_client.py), not a
concrete SDK type, so adapters never import anything Caspian-specific either.
"""

from __future__ import annotations

from app.application.ports.channel_port import SendResult
from app.domain.value_objects.channel import Channel
from app.integrations.caspian_client import CaspianClientProtocol


class CaspianGateway:
    def __init__(self, caspian_client: CaspianClientProtocol) -> None:
        self._client = caspian_client

    def send(self, channel: Channel, recipient: str, payload: dict) -> SendResult:
        result = self._client.send(channel.value, recipient, payload)
        return SendResult(
            success=result.success,
            external_message_ref=result.external_message_ref,
            error=result.error,
            conversation_ref=result.conversation_ref,
        )
