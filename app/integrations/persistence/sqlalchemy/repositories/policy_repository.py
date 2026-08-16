"""SQLAlchemy implementation of PolicyRepositoryPort.

Translates between models.Policy rows and PolicyTopicDTO — the Policy table stores one row
per (industry_pack, topic, version); `is_active` marks which version is currently in force.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.application.dto.policy_pack_dto import PolicyTopicDTO
from app.application.ports.policy_repository_port import PolicyRepositoryPort
from app.integrations.persistence.sqlalchemy import models


class SqlAlchemyPolicyRepository(PolicyRepositoryPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(self, industry_pack: str, topic: str) -> PolicyTopicDTO | None:
        stmt = select(models.Policy).where(
            models.Policy.industry_pack == industry_pack,
            models.Policy.topic == topic,
            models.Policy.is_active.is_(True),
        )
        row = self._session.execute(stmt).scalar_one_or_none()
        return _to_dto(row) if row is not None else None

    def list_active(self, industry_pack: str) -> list[PolicyTopicDTO]:
        stmt = select(models.Policy).where(
            models.Policy.industry_pack == industry_pack,
            models.Policy.is_active.is_(True),
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_to_dto(row) for row in rows]

    def replace_pack(self, industry_pack: str, version: str, topics: list[PolicyTopicDTO]) -> None:
        self._session.execute(
            update(models.Policy)
            .where(models.Policy.industry_pack == industry_pack, models.Policy.is_active.is_(True))
            .values(is_active=False)
        )
        for topic_dto in topics:
            self._session.add(
                models.Policy(
                    industry_pack=industry_pack,
                    topic=topic_dto.topic,
                    required_roles=list(topic_dto.required_roles),
                    version=version,
                    is_active=True,
                )
            )
        self._session.flush()


def _to_dto(row: models.Policy) -> PolicyTopicDTO:
    return PolicyTopicDTO(topic=row.topic, required_roles=list(row.required_roles))
