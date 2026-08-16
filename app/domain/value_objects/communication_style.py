"""CommunicationStyle value object — the closed set ChannelSelectionRules maps to a channel.
Not persisted (no column uses it yet); it exists purely as the input side of the
deterministic channel-selection rule table.
"""

from enum import Enum


class CommunicationStyle(str, Enum):
    URGENT = "urgent"
    FORMAL = "formal"
    DISCUSSION = "discussion"
    COMMUNITY = "community"
