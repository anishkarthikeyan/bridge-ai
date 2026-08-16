"""PolicyPackDTO — the validated shape of one YAML policy pack (policies/*.yaml), e.g.
policies/software.yaml. Fixes the contract between the pack file and the Policy table before
either a loader or the policy engine exists (both are Phase 3 — no loading logic here).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PolicyTopicDTO(BaseModel):
    topic: str
    required_roles: list[str] = Field(min_length=1)


class PolicyPackDTO(BaseModel):
    industry_pack: str
    version: str = "1"
    topics: list[PolicyTopicDTO]
