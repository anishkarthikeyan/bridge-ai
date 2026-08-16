"""RoleResolution value object — RoleResolver's output. Always returned, never raised: a
failed resolution is `resolved=False` with a `failure_reason`, not an exception or a None
the caller has to interpret — see RoleResolver for why that matters.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects.candidate_contact import CandidateContact
from app.domain.value_objects.channel import Channel


@dataclass(frozen=True)
class RoleResolution:
    role: str
    resolved: bool
    participant: CandidateContact | None = None
    preferred_channel: Channel | None = None
    address: str | None = None
    """The concrete channel identity to send to — participant.email or
    participant.telegram_handle, depending on preferred_channel."""
    failure_reason: str | None = None
