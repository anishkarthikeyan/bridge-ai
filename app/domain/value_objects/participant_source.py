"""ParticipantSource value object — how a Participant entered a case's Conversation Graph:
explicitly (on the original thread) or inferred (added by stakeholder detection because
their role was required but absent). Same closed-set-enum pattern as the other value
objects in this package.
"""

from enum import Enum


class ParticipantSource(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
