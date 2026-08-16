"""DecisionStatus value object — the execution lifecycle of a Decision. Replaces the Phase 3
`Decision.executed: bool`, which could only represent "not yet" or "done" and had no way to
express that dispatch is in flight or failed.
"""

from enum import Enum


class DecisionStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
