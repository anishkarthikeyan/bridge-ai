"""ChannelRegistry — determines which channels are currently available, and applies
deterministic preferred/fallback selection among them.

Availability is constructor-injected as an explicit set, not self-discovered by probing
adapters — that keeps this a pure domain service with no I/O. Deciding *what* is actually
available (e.g. which channels have a configured adapter and credentials) is an
integrations-layer concern, out of scope here (see "DO NOT IMPLEMENT: Email/Telegram/Slack
Adapter"); this registry is the deterministic policy that will consume whatever that future
wiring reports, via the constructor.

Two hard guarantees, both enforced structurally rather than by convention:
  - never raises because an adapter is missing — unavailable/no-channel-at-all cases return
    None, they never throw;
  - never returns a channel outside `available_channels` — every method filters through the
    same `_available` set.
"""

from __future__ import annotations

from app.domain.value_objects.channel import Channel

DEFAULT_FALLBACK_ORDER: tuple[Channel, ...] = (
    Channel.EMAIL,
    Channel.TELEGRAM,
    Channel.SLACK,
    Channel.DISCORD,
)


class ChannelRegistry:
    def __init__(
        self,
        available_channels: set[Channel] | None = None,
        fallback_order: tuple[Channel, ...] = DEFAULT_FALLBACK_ORDER,
    ) -> None:
        self._available: set[Channel] = (
            set(available_channels)
            if available_channels is not None
            else set(DEFAULT_FALLBACK_ORDER)
        )
        self._fallback_order = fallback_order

    def available_channels(self) -> tuple[Channel, ...]:
        """Currently available channels, in deterministic fallback-priority order."""
        return tuple(c for c in self._fallback_order if c in self._available)

    def is_available(self, channel: Channel) -> bool:
        return channel in self._available

    def preferred_channel(self, preferred: Channel) -> Channel | None:
        """Returns `preferred` if it's available; otherwise deterministically falls back to
        the next available channel in fallback order. Returns None only if no configured
        channel is available at all — this never raises.
        """
        if self.is_available(preferred):
            return preferred
        return self.fallback_channel(exclude=preferred)

    def fallback_channel(self, exclude: Channel | None = None) -> Channel | None:
        """The next available channel in fallback order, optionally skipping one. None if
        nothing is available."""
        for channel in self.available_channels():
            if channel != exclude:
                return channel
        return None
