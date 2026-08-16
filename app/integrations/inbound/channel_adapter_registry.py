"""ChannelAdapterRegistry — maps a Channel to its ChannelPort implementation. Used on both
sides: BridgeAgentHandler resolves an adapter to parse an inbound event; DispatchMessageUseCase
resolves one to send an OutboundAction. Same registry, same lookup, both directions —
"Inbound Routing" and "Outbound Routing" (architecture doc, Phase 5) are this one class used
from two call sites, not two separate mechanisms.
"""

from __future__ import annotations

from app.application.ports.channel_port import ChannelPort
from app.domain.value_objects.channel import Channel


class ChannelAdapterRegistry:
    def __init__(self, adapters: dict[Channel, ChannelPort]) -> None:
        self._adapters = dict(adapters)

    def get(self, channel: Channel) -> ChannelPort:
        try:
            return self._adapters[channel]
        except KeyError as exc:
            raise ValueError(f"No adapter registered for channel '{channel.value}'") from exc

    def configured_channels(self) -> frozenset[Channel]:
        return frozenset(self._adapters.keys())
