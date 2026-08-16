"""BridgeAgentHandler — the single Caspian-registered entrypoint for every inbound channel
event, on every channel. Registered exactly once, at composition-root time (see
app/infrastructure/di_container.py) — architecture doc's "only one Caspian handler" rule is
enforced there (CaspianClient.register_handler raises if called twice) and structurally
here: this class contains no per-channel branching on business rules, only a lookup into
ChannelAdapterRegistry and a hand-off to inbound routing.
"""

from __future__ import annotations

from typing import Protocol

from app.application.dto.inbound_message import InboundMessage
from app.domain.value_objects.channel import Channel
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry


class InboundRouter(Protocol):
    """What BridgeAgentHandler hands a parsed message to — satisfied by
    IngestInboundMessageUseCase (app/application/use_cases/ingest_inbound_message.py)."""

    def handle(self, message: InboundMessage) -> object: ...


class BridgeAgentHandler:
    def __init__(
        self, channel_adapter_registry: ChannelAdapterRegistry, inbound_router: InboundRouter
    ) -> None:
        self._channel_adapter_registry = channel_adapter_registry
        self._inbound_router = inbound_router

    def __call__(self, channel: str, raw_payload: dict) -> None:
        adapter = self._channel_adapter_registry.get(Channel(channel))
        message = adapter.parse_inbound(raw_payload)
        self._inbound_router.handle(message)
