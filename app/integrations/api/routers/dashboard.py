"""GET /dashboard/summary (Phase 6.5 Part 12) — one lightweight aggregate call so the future
frontend doesn't have to run several separate list/count queries itself. Reuses
CaseRepositoryPort.list_cases (Part 11's own listing query, with no filter/limit) and
app/application/dto/case_mappers.py's aggregation — no second database aggregation system.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.application.dto.case_mappers import build_dashboard_summary
from app.application.dto.case_snapshot_dto import DashboardSummaryDTO
from app.application.ports.case_repository_port import CaseRepositoryPort
from app.integrations.api.dependencies import get_case_repository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryDTO)
def get_dashboard_summary(
    case_repository: CaseRepositoryPort = Depends(get_case_repository),
) -> DashboardSummaryDTO:
    cases, _total = case_repository.list_cases(limit=None)
    return build_dashboard_summary(cases, now=datetime.now(UTC))
