"""RoleDirectoryLoader — reads a YAML role directory (policies/role_directory.yaml),
validates its schema, and returns an immutable, role-indexed mapping of CandidateContact.
Same pattern as PolicyLoader (Phase 3): the one place in app/domain/ allowed to touch a
filesystem and pyyaml, everything downstream gets frozen value objects only.

Separate file from policies/software.yaml on purpose: that file is topic policy (what a
topic requires); this one is *people* — who can actually fill a required role. Conflating
the two would mean every new hire or team change touches the same file as topic rules.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from app.domain.exceptions import PolicyValidationError
from app.domain.value_objects.candidate_contact import CandidateContact

RoleDirectory = MappingProxyType[str, tuple[CandidateContact, ...]]

_REQUIRED_CANDIDATE_KEYS = {"role", "name"}


class RoleDirectoryLoader:
    def load(self, path: str | Path) -> RoleDirectory:
        raw = self._read_yaml(Path(path))
        return self._parse_directory(raw, source=str(path))

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError as exc:
            raise PolicyValidationError(f"Role directory not found: {path}") from exc
        except yaml.YAMLError as exc:
            raise PolicyValidationError(
                f"Role directory is not valid YAML: {path} ({exc})"
            ) from exc

        if not isinstance(data, dict):
            raise PolicyValidationError(
                f"Role directory must be a mapping at the top level: {path}"
            )
        return data

    def _parse_directory(self, raw: dict[str, Any], source: str) -> RoleDirectory:
        candidates_raw = raw.get("candidates")
        if not isinstance(candidates_raw, list) or not candidates_raw:
            raise PolicyValidationError(
                f"{source}: 'candidates' is required and must be a non-empty list"
            )

        by_role: dict[str, list[CandidateContact]] = {}
        for entry in candidates_raw:
            candidate = self._parse_candidate(entry, source)
            by_role.setdefault(candidate.role, []).append(candidate)

        return MappingProxyType({role: tuple(cs) for role, cs in by_role.items()})

    @staticmethod
    def _parse_candidate(raw: Any, source: str) -> CandidateContact:
        if not isinstance(raw, dict):
            raise PolicyValidationError(f"{source}: each candidate entry must be a mapping")

        missing_keys = _REQUIRED_CANDIDATE_KEYS - raw.keys()
        if missing_keys:
            raise PolicyValidationError(
                f"{source}: candidate entry missing required keys: {sorted(missing_keys)}"
            )

        role, name = raw["role"], raw["name"]
        if not isinstance(role, str) or not role:
            raise PolicyValidationError(f"{source}: 'role' must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise PolicyValidationError(f"{source}: 'name' must be a non-empty string")

        email = raw.get("email")
        telegram_handle = raw.get("telegram_handle")
        if email is None and telegram_handle is None:
            raise PolicyValidationError(
                f"{source}: '{name}' ({role}) has no email or telegram_handle — unreachable"
            )

        try:
            preference_rank = int(raw.get("preference_rank", 0))
        except (TypeError, ValueError) as exc:
            raise PolicyValidationError(
                f"{source}: '{name}'.preference_rank must be an int"
            ) from exc

        return CandidateContact(
            name=name,
            role=role,
            email=email,
            telegram_handle=telegram_handle,
            preference_rank=preference_rank,
        )
