"""ResolutionState value object — the Case lifecycle (architecture doc §5, agent workflow).

Escalation is not a distinct state machine: it is AWAITING_RESPONSE re-entered with a
different recipient/channel/urgency, decided fresh each time by the (not-yet-implemented)
reasoning engine. HUMAN_HANDOFF is reached only after autonomous options are exhausted.
"""

from enum import Enum


class ResolutionState(str, Enum):
    OPEN = "open"
    AWAITING_RESPONSE = "awaiting_response"
    ESCALATED = "escalated"
    HUMAN_HANDOFF = "human_handoff"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"
