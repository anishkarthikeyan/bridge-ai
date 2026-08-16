"""Read-only case inspection endpoints (Phase 6.5 Part 11): GET /cases, GET /cases/{id}, GET
/cases/{id}/timeline, GET /cases/{id}/decisions. Every response is a DTO
(app/application/dto/case_snapshot_dto.py) built by app/application/dto/case_mappers.py —
never a SQLAlchemy model or a domain entity directly (Part 11: "Never expose SQLAlchemy
models directly").

`status`/`priority` filters are validated against the real closed-set enums here and rejected
with 400 for anything else (Part 13); `topic` is intentionally unvalidated free text — a
topic outside the current policy pack is a normal, already-supported case shape (see
LoadPolicyNode's "degrade, don't fail" behavior for an out-of-pack topic), not an invalid
request.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.application.dto.case_mappers import (
    build_timeline,
    to_case_list_item,
    to_case_snapshot,
    to_decision_dto,
)
from app.application.dto.case_snapshot_dto import (
    CaseListResponseDTO,
    CaseSnapshotDTO,
    DecisionDTO,
    TimelineEntryDTO,
)
from app.application.ports.case_repository_port import CaseRepositoryPort
from app.domain.entities.case import Case
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_state import ResolutionState
from app.integrations.api.dependencies import get_case_repository

router = APIRouter(prefix="/cases", tags=["cases"])


def _validate_enum(value: str | None, enum_cls: type, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return enum_cls(value).value  # type: ignore[no-any-return]
    except ValueError as exc:
        valid = ", ".join(e.value for e in enum_cls)  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=400, detail=f"Invalid {field_name} '{value}'; expected one of: {valid}"
        ) from exc


def _get_case_or_404(case_repository: CaseRepositoryPort, case_id: UUID) -> Case:
    case = case_repository.get_by_id(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


@router.get("", response_model=CaseListResponseDTO)
def list_cases(
    status: str | None = Query(default=None, description="Filter by resolution_status"),
    priority: str | None = Query(default=None, description="Filter by priority"),
    topic: str | None = Query(default=None, description="Filter by topic"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    case_repository: CaseRepositoryPort = Depends(get_case_repository),
) -> CaseListResponseDTO:
    status = _validate_enum(status, ResolutionState, "status")
    priority = _validate_enum(priority, Priority, "priority")

    cases, total = case_repository.list_cases(
        status=status, priority=priority, topic=topic, limit=limit, offset=offset
    )
    return CaseListResponseDTO(
        items=[to_case_list_item(c) for c in cases], total=total, limit=limit, offset=offset
    )


@router.get("/{case_id}", response_model=CaseSnapshotDTO)
def get_case(
    case_id: UUID, case_repository: CaseRepositoryPort = Depends(get_case_repository)
) -> CaseSnapshotDTO:
    return to_case_snapshot(_get_case_or_404(case_repository, case_id))


@router.get("/{case_id}/timeline", response_model=list[TimelineEntryDTO])
def get_case_timeline(
    case_id: UUID, case_repository: CaseRepositoryPort = Depends(get_case_repository)
) -> list[TimelineEntryDTO]:
    return build_timeline(_get_case_or_404(case_repository, case_id))


@router.get("/{case_id}/decisions", response_model=list[DecisionDTO])
def get_case_decisions(
    case_id: UUID, case_repository: CaseRepositoryPort = Depends(get_case_repository)
) -> list[DecisionDTO]:
    case = _get_case_or_404(case_repository, case_id)
    return [to_decision_dto(d) for d in case.decisions]
