"""Decision entity — one audited reasoning step for a case: which node acted, what it saw,
what it chose, and how confident it was. The explainability record the LLM-boundary rule
depends on (a node's chosen_action must be traceable to either a deterministic rule or a
labeled LLM output — never an unexplained action). Every brain node persists exactly one of
these, per its required lifecycle (architecture doc, Phase 4 Change 3).

`status` (Phase 4) replaces the Phase 3 `executed: bool`, which could only represent
"not yet" or "done." A boolean can't express that dispatch is in flight or that it failed —
`status` can: PENDING (recorded, not yet acted on) -> EXECUTING (dispatch in progress) ->
SUCCESS or FAILED. That range is what makes retries, replay, and an accurate dashboard state
possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.value_objects.decision_status import DecisionStatus


@dataclass
class Decision:
    id: UUID
    case_id: UUID
    node_name: str
    reasoning_summary: str
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    chosen_action: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    status: DecisionStatus = DecisionStatus.PENDING
    created_at: datetime | None = None
