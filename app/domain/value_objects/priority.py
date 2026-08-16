"""Priority value object — the closed set a Case's `priority` column takes, and the output
of the (deterministic) Priority Engine. Same closed-set-enum pattern as the other value
objects in this package.
"""

from enum import Enum


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
