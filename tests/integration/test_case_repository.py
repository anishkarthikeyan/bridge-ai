"""SqlAlchemyCaseRepository tests against a real Postgres (Phase 6.5 Part 15) —
`list_cases` pagination/filtering, `list_due_for_followup`'s due-case discovery, and its
`SKIP LOCKED` duplicate-dispatch prevention across two genuinely concurrent
sessions/transactions (standing in for two scheduler processes/ticks). Skips cleanly if
Postgres isn't reachable, rather than failing unrelated tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.domain.entities.case import Case
from app.domain.entities.conversation import Conversation
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.priority import Priority
from app.infrastructure.config import get_settings
from app.infrastructure.db import SessionLocal
from app.integrations.persistence.sqlalchemy.repositories.case_repository import (
    SqlAlchemyCaseRepository,
)


def _database_reachable() -> bool:
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


pytestmark = pytest.mark.skipif(
    not _database_reachable(), reason="Postgres not reachable at DATABASE_URL — skipping"
)


@pytest.fixture
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_list_cases_filters_by_topic_and_paginates(session) -> None:
    repo = SqlAlchemyCaseRepository(session)
    topic = f"test-topic-{uuid4().hex[:8]}"
    for _ in range(3):
        repo.add(Case(id=uuid4(), topic=topic, priority=Priority.HIGH))
    session.flush()

    page, total = repo.list_cases(topic=topic, limit=2, offset=0)
    assert total == 3
    assert len(page) == 2

    page2, total2 = repo.list_cases(topic=topic, limit=2, offset=2)
    assert total2 == 3
    assert len(page2) == 1

    everything, total3 = repo.list_cases(topic=topic, limit=None)
    assert total3 == 3
    assert len(everything) == 3


def test_list_cases_filters_by_status_and_priority(session) -> None:
    repo = SqlAlchemyCaseRepository(session)
    topic = f"test-topic-{uuid4().hex[:8]}"
    repo.add(Case(id=uuid4(), topic=topic, priority=Priority.LOW))
    repo.add(Case(id=uuid4(), topic=topic, priority=Priority.HIGH))
    session.flush()

    high_only, total = repo.list_cases(topic=topic, priority="high")
    assert total == 1
    assert high_only[0].priority == Priority.HIGH

    open_only, total_open = repo.list_cases(topic=topic, status="open")
    assert total_open == 2


def test_list_due_for_followup_only_returns_due_open_cases(session) -> None:
    repo = SqlAlchemyCaseRepository(session)
    now = datetime.now(UTC)
    marker = f"due-test-{uuid4().hex[:8]}"

    due = repo.add(Case(id=uuid4(), topic=marker, next_check_at=now - timedelta(hours=1)))
    not_due = repo.add(Case(id=uuid4(), topic=marker, next_check_at=now + timedelta(hours=1)))
    never_dispatched = repo.add(Case(id=uuid4(), topic=marker, next_check_at=None))
    session.flush()

    results = {c.id for c in repo.list_due_for_followup(now, limit=50)}
    assert due.id in results
    assert not_due.id not in results
    assert never_dispatched.id not in results


def test_list_due_for_followup_skip_locked_prevents_duplicate_claims() -> None:
    """Two independent sessions/transactions standing in for two scheduler processes/ticks —
    Part 8's "Scheduler Safety": the second must not see a case the first still holds locked."""
    engine = create_engine(get_settings().database_url)
    session_factory = sessionmaker(bind=engine)
    session_a, session_b = session_factory(), session_factory()
    try:
        repo_a = SqlAlchemyCaseRepository(session_a)
        now = datetime.now(UTC)
        case = repo_a.add(
            Case(id=uuid4(), topic="lock-test", next_check_at=now - timedelta(hours=1))
        )
        session_a.commit()  # must be committed for session_b's separate transaction to see it

        claimed_a = repo_a.list_due_for_followup(now, limit=50)  # opens+holds the row lock
        assert any(c.id == case.id for c in claimed_a)

        repo_b = SqlAlchemyCaseRepository(session_b)
        claimed_b = repo_b.list_due_for_followup(
            now, limit=50
        )  # SKIP LOCKED: excluded, not blocked
        assert all(c.id != case.id for c in claimed_b)

        session_a.commit()  # release session_a's lock

        # Cleanup: this test (uniquely in this file) commits real data, so it must also
        # remove it — every other test here relies on rollback() discarding its own.
        session_a.execute(text("DELETE FROM cases WHERE id = :id"), {"id": str(case.id)})
        session_a.commit()
    finally:
        session_a.rollback()
        session_b.rollback()
        session_a.close()
        session_b.close()
        engine.dispose()


def test_conversation_registered_by_dispatch_survives_a_fresh_session(session) -> None:
    """Part 4 (Phase 6.6.6): the cross-channel-continuity Conversation
    DispatchMessageUseCase registers is durably persisted — not an in-memory artifact of the
    session that created it. Written with one session/repository, read back with a
    completely independent one (a fresh engine + connection), the same way a real process
    restart or a second app instance would see it.
    """
    repo = SqlAlchemyCaseRepository(session)
    case = repo.add(Case(id=uuid4(), topic="payment_system"))
    conversation = repo.add_conversation(
        case.id,
        Conversation(
            id=uuid4(),
            case_id=case.id,
            channel=Channel.TELEGRAM,
            external_thread_ref="conv_test_xyz",
        ),
    )
    assert conversation.external_thread_ref == "conv_test_xyz"  # sanity: what was written
    session.commit()

    verify_engine = create_engine(get_settings().database_url)
    verify_session_factory = sessionmaker(bind=verify_engine)
    verify_session = verify_session_factory()
    try:
        fresh_repo = SqlAlchemyCaseRepository(verify_session)

        fresh_case = fresh_repo.get_by_id(case.id)
        assert fresh_case is not None
        assert len(fresh_case.conversations) == 1
        assert fresh_case.conversations[0].channel == Channel.TELEGRAM
        assert fresh_case.conversations[0].external_thread_ref == "conv_test_xyz"

        found = fresh_repo.find_by_conversation_ref("telegram", "conv_test_xyz")
        assert found is not None
        assert found.id == case.id
    finally:
        verify_session.execute(text("DELETE FROM cases WHERE id = :id"), {"id": str(case.id)})
        verify_session.commit()
        verify_session.close()
        verify_engine.dispose()
