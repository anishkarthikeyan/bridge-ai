"""CandidateContact value object — one known, named person who can fill a role, with
however many channel identities they have and a deterministic preference rank. Loaded from
policies/role_directory.yaml by RoleDirectoryLoader; consumed by RoleResolver. Not a
Participant (app/domain/entities/participant.py) — a Participant is case-scoped (someone
already on a case's thread); a CandidateContact is directory-scoped (someone who *could* be
brought onto a case for a given role, before they ever appear on one).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateContact:
    name: str
    role: str
    email: str | None = None
    telegram_handle: str | None = None
    preference_rank: int = 0
    """Lower is more preferred. Ties break on name — see RoleResolver — so candidate
    selection never depends on dict/list ordering or any other incidental factor."""
