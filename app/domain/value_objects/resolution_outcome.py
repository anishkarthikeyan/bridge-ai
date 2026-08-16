"""ResolutionOutcome value object — the exactly-one-of-four result ResolutionEvaluator
returns after every reply (architecture doc, Phase 6 Change 1). No other values are allowed.
"""

from enum import Enum


class ResolutionOutcome(str, Enum):
    WAIT = "wait"
    FOLLOW_UP = "follow_up"
    ESCALATE = "escalate"
    RESOLVED = "resolved"
