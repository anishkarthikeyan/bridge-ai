"""ChannelSelectionRules — deterministic, configurable mapping from a communication style to
a recommended channel. No AI: given a style, this looks a channel up in a table, it never
infers or generates one.

Deliberately decoupled from the Channel value object (email/telegram — the channels this
build actually has adapters for): the rule table below also recommends slack and discord,
which have no adapter yet. Recommending a channel and being able to dispatch to it are
separate concerns — dispatch (out of scope here) is what will need to know which recommended
channels are actually actionable.

"Rules should be configurable" — the default table below is just the constructor default;
pass a different mapping to override it entirely, or use with_rule() to change one entry
without touching the rest.
"""

from __future__ import annotations

from types import MappingProxyType

from app.domain.value_objects.communication_style import CommunicationStyle

DEFAULT_CHANNEL_RULES: MappingProxyType[CommunicationStyle, str] = MappingProxyType(
    {
        CommunicationStyle.URGENT: "telegram",
        CommunicationStyle.FORMAL: "email",
        CommunicationStyle.DISCUSSION: "slack",
        CommunicationStyle.COMMUNITY: "discord",
    }
)


class ChannelSelectionRules:
    def __init__(self, rules: dict[CommunicationStyle, str] | None = None) -> None:
        self._rules: dict[CommunicationStyle, str] = (
            dict(rules) if rules is not None else dict(DEFAULT_CHANNEL_RULES)
        )

    def select(self, style: CommunicationStyle) -> str:
        try:
            return self._rules[style]
        except KeyError as exc:
            raise ValueError(f"No channel rule configured for style '{style}'") from exc

    def with_rule(self, style: CommunicationStyle, channel: str) -> ChannelSelectionRules:
        """Returns a new rule set with one mapping overridden; this instance is unchanged."""
        updated = dict(self._rules)
        updated[style] = channel
        return ChannelSelectionRules(updated)
