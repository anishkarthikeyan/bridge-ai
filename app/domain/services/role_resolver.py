"""RoleResolver — deterministic resolution of a missing role to a specific, reachable
person. No AI: candidate ranking is a total order (preference_rank, then name), and channel
selection is a lookup against ChannelRegistry's availability, both fully explainable.

The chain this implements, per role:

    Role -> Participant (best REACHABLE candidate among those known for the role)
         -> Preferred Contact (that candidate's identity for the chosen channel)
         -> Preferred Channel (the highest-priority channel both the system and the
                                candidate can actually be reached on)

"Best" means best reachable, not merely best-ranked: candidates are tried in rank order, and
for each one every available channel is tried in the registry's priority order, so a
top-ranked candidate with no usable channel identity yields to the next-ranked one who has
one — the point of resolving a role is finding someone you can actually reach, not naming
someone you can't.

Two guarantees, both structural:
  - never returns an unknown participant — the result can only ever be one of the
    `candidates` passed in, never fabricated;
  - never raises — a role with no candidates, or where nobody known for it is reachable on
    any available channel, comes back as `RoleResolution(resolved=False,
    failure_reason=...)`, the same never-throw contract ChannelRegistry already established
    in Phase 4.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.services.channel_registry import ChannelRegistry
from app.domain.value_objects.candidate_contact import CandidateContact
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.role_resolution import RoleResolution


class RoleResolver:
    def __init__(self, channel_registry: ChannelRegistry | None = None) -> None:
        self._channel_registry = channel_registry or ChannelRegistry()

    def resolve(self, role: str, candidates: Sequence[CandidateContact]) -> RoleResolution:
        role_candidates = [c for c in candidates if c.role == role]
        if not role_candidates:
            return RoleResolution(
                role=role, resolved=False, failure_reason=f"No known candidate for role '{role}'"
            )

        ranked = self._rank(role_candidates)
        available_channels = self._channel_registry.available_channels()

        for candidate in ranked:
            for channel in available_channels:
                address = self._address_for(candidate, channel)
                if address is not None:
                    return RoleResolution(
                        role=role,
                        resolved=True,
                        participant=candidate,
                        preferred_channel=channel,
                        address=address,
                    )

        return RoleResolution(
            role=role,
            resolved=False,
            participant=ranked[0],
            failure_reason=(
                f"No candidate for role '{role}' is reachable on any available channel"
            ),
        )

    @staticmethod
    def _rank(candidates: Sequence[CandidateContact]) -> list[CandidateContact]:
        """Lowest preference_rank first; ties break alphabetically by name. Fully
        deterministic regardless of the input list's order.
        """
        return sorted(candidates, key=lambda c: (c.preference_rank, c.name))

    @staticmethod
    def _address_for(candidate: CandidateContact, channel: Channel) -> str | None:
        if channel == Channel.EMAIL:
            return candidate.email
        if channel == Channel.TELEGRAM:
            return candidate.telegram_handle
        return None
