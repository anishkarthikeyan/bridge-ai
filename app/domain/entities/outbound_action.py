"""OutboundAction entity — the dispatch-ready object a PENDING Decision becomes. This is the
*only* input Dispatch (app/application/use_cases/dispatch_message.py) or a ChannelPort
adapter ever sees; neither touches a Decision or a Case directly (architecture doc, Phase 5
rule: "Dispatch only receives OutboundAction").

`decision_id` (Change 4) is what lets Dispatch report back: after attempting a send, it's
the referenced Decision whose status moves EXECUTING -> SUCCESS/FAILED, not this object —
OutboundAction itself carries no status. It's a snapshot of what to do, built once from an
already-made decision; it is not itself a decision.

Supersedes the Phase 1 stub application/dto/outbound_message.py, which this build removes —
see the Phase 5 architectural observations for why.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.value_objects.channel import Channel
from app.domain.value_objects.priority import Priority


@dataclass(frozen=True)
class Recipient:
    name: str
    address: str
    """The channel-specific identity to send to — an email address or a Telegram handle,
    depending on the OutboundAction's channel."""


@dataclass(frozen=True)
class OutboundAction:
    recipient: Recipient
    channel: Channel
    message: str
    priority: Priority
    follow_up_at: datetime | None
    decision_id: UUID
    case_id: UUID
