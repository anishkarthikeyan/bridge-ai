"""MessageDirection value object — the closed set a Message's `direction` column takes.
Same pattern as Channel / ResolutionState / CommunicationHealth, applied consistently.
"""

from enum import Enum


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
