"""Shared FastAPI dependencies for the read APIs (Phase 6.5 Part 11) — one place that builds
a request-scoped CaseRepositoryPort from a request-scoped Session, so every router asks for
the port, never the concrete SQLAlchemy session/class directly.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.infrastructure.db import get_db
from app.integrations.persistence.sqlalchemy.repositories.case_repository import (
    SqlAlchemyCaseRepository,
)


def get_case_repository(db: Session = Depends(get_db)) -> CaseRepositoryPort:
    return SqlAlchemyCaseRepository(db)
