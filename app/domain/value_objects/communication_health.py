"""CommunicationHealth value object — a coarse, dashboard-facing signal for how well a
case's conversation is progressing, independent of ResolutionState (a case can be OPEN and
HEALTHY, or AWAITING_RESPONSE and AT_RISK).

Persisted on Case from the start (Phase 2) even though nothing computes it yet — the future
dashboard visualizes this field, and a value present from day one avoids a later migration
just to add it.
"""

from enum import Enum


class CommunicationHealth(str, Enum):
    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    STALLED = "stalled"
    CRITICAL = "critical"
