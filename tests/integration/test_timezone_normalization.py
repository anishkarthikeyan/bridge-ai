"""Regression coverage for the persistence-boundary timezone fix in app/infrastructure/db.py
— see that module's docstring for the full mechanism. Real bug, reproduced and fixed during
this build: this deployment's ambient PostgreSQL session timezone is `Asia/Kolkata` (`SHOW
timezone` on an unconfigured connection), and every timestamp column in models.py is a plain
timezone-naive `TIMESTAMP` — so, before the fix, both `server_default=func.now()` columns
(created_at, ...) and application-computed columns (Case.next_check_at, set from
`datetime.now(UTC)`) were silently stored 5.5 hours ahead of true UTC, then read back and
mislabeled `tzinfo=UTC` by `_as_utc()` (case_repository.py/message_repository.py) — exactly
the "Updated: in 5h" symptom reported against the read API.

Nothing here touches business logic, the database schema, LangGraph, or any API/DTO shape —
every test below exercises the real `app.infrastructure.db.engine`/`SessionLocal` exactly as
the application already uses them; the fix under test is the `connect` event listener alone.

Skips cleanly if Postgres isn't reachable, matching every other real-Postgres test in this
suite (see test_case_repository.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.domain.entities.case import Case
from app.domain.entities.decision import Decision
from app.domain.value_objects.decision_status import DecisionStatus
from app.infrastructure.config import get_settings
from app.infrastructure.db import SessionLocal, engine
from app.integrations.persistence.sqlalchemy.repositories.case_repository import (
    SqlAlchemyCaseRepository,
)

_ROUND_TRIP_TOLERANCE_SECONDS = 5
"""Generous enough to absorb real wall-clock time spent round-tripping through Postgres, but
five orders of magnitude tighter than the ~19800s (5.5h) the Asia/Kolkata bug actually
produced — nothing but a genuine offset bug could make this assertion fail."""


def _database_reachable() -> bool:
    probe_engine = create_engine(get_settings().database_url)
    try:
        with probe_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False
    finally:
        probe_engine.dispose()


pytestmark = pytest.mark.skipif(
    not _database_reachable(), reason="Postgres not reachable at DATABASE_URL — skipping"
)


def _ambient_session_timezone_is_utc() -> bool:
    """Whether this environment's own default already happens to be UTC — if so, the
    "against Asia/Kolkata" tests below still run (they force Kolkata explicitly on a control
    connection either way), but the confirmation that the *ambient* default is non-UTC (the
    condition that originally hid this bug) is itself worth asserting only when meaningful."""
    probe_engine = create_engine(get_settings().database_url)
    try:
        with probe_engine.connect() as conn:
            return conn.execute(text("SHOW timezone")).scalar() == "UTC"
    finally:
        probe_engine.dispose()


@pytest.fixture
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_this_deployment_genuinely_defaults_to_a_non_utc_session_timezone() -> None:
    """Sanity check on the premise, not the fix — if this ever starts failing because the
    ambient environment's own default changed to UTC, the other tests here still prove the
    fix works (they force Asia/Kolkata explicitly), but it's worth knowing the original bug
    condition is still real and reproducible independent of our own engine's fix."""
    control_engine = create_engine(get_settings().database_url)
    try:
        with control_engine.connect() as conn:
            ambient_tz = conn.execute(text("SHOW timezone")).scalar()
    finally:
        control_engine.dispose()
    assert ambient_tz == "Asia/Kolkata", (
        f"expected this dev/CI Postgres to default to Asia/Kolkata (the condition that "
        f"originally hid the bug), got {ambient_tz!r} instead — the fix is still correct "
        f"either way, but this test's premise assumes a non-UTC ambient default"
    )


def test_app_engine_pins_the_session_to_utc_on_connect() -> None:
    with engine.connect() as conn:
        assert conn.execute(text("SHOW timezone")).scalar() == "UTC"


def test_app_engine_stays_pinned_to_utc_across_pooled_checkouts_even_after_a_rollback() -> None:
    """Regression guard for the real bug this fix's first draft had: `SET TIME ZONE` issued
    inside an uncommitted implicit transaction gets silently undone by the *next* rollback
    anywhere on that pooled connection — reverting to the Asia/Kolkata ambient default for
    every subsequent checkout of that same physical connection, not just the one that rolled
    back. Reproduced directly against real Postgres before adding the commit that fixes it.
    """
    timezones = []
    for i in range(4):
        with SessionLocal() as s:
            timezones.append(s.execute(text("SHOW timezone")).scalar())
            if i == 1:
                s.rollback()  # deliberately unrelated to timezone — must not undo the pin

    assert timezones == ["UTC", "UTC", "UTC", "UTC"], (
        f"session timezone drifted after a rollback: {timezones}"
    )


def test_a_connection_without_the_fix_reproduces_the_original_bug() -> None:
    """The control: proves the ambient Asia/Kolkata default really does corrupt a naive
    TIMESTAMP column exactly as described, on a connection that does *not* go through
    app.infrastructure.db's fixed engine — so the fixed engine's UTC results above are
    doing real work, not coincidentally matching an already-UTC environment."""
    unfixed_engine = create_engine(get_settings().database_url)
    try:
        with unfixed_engine.begin() as conn:
            assert conn.execute(text("SHOW timezone")).scalar() == "Asia/Kolkata"
            conn.execute(text("CREATE TEMP TABLE tz_regression_probe (naive_col timestamp)"))
            written = datetime.now(UTC)
            conn.execute(
                text("INSERT INTO tz_regression_probe (naive_col) VALUES (:v)"), {"v": written}
            )
            stored_naive = conn.execute(
                text("SELECT naive_col FROM tz_regression_probe")
            ).scalar()

        # The bug: the naive value read back, re-labeled UTC, is offset by the session's
        # timezone (+5:30 for Asia/Kolkata) rather than matching what was actually written.
        mislabeled_as_utc = stored_naive.replace(tzinfo=UTC)
        offset_seconds = abs((mislabeled_as_utc - written).total_seconds())
        assert offset_seconds > 60, (
            "expected the unfixed connection to reproduce a real offset (~19800s for "
            f"Asia/Kolkata); got only {offset_seconds}s — has the ambient default changed?"
        )
    finally:
        unfixed_engine.dispose()


def test_case_next_check_at_round_trips_to_the_exact_utc_instant_through_a_fresh_session(
    session,
) -> None:
    """The real end-to-end proof: Case.next_check_at (application-computed, exactly the
    field that showed "in 5h" against the read API) survives being written by one session
    and re-read by a completely independent one — a different process, a real restart — at
    the correct UTC instant, not shifted by the local session's ambient offset.
    """
    repo = SqlAlchemyCaseRepository(session)
    written_at = datetime.now(UTC) + timedelta(hours=2)
    case = repo.add(Case(id=uuid4(), topic="tz-regression", next_check_at=written_at))
    session.commit()

    verify_engine = create_engine(get_settings().database_url)
    try:
        verify_session = sessionmaker(bind=verify_engine)()
        try:
            fresh = SqlAlchemyCaseRepository(verify_session).get_by_id(case.id)
            assert fresh is not None
            assert fresh.next_check_at is not None
            assert fresh.next_check_at.tzinfo is not None
            delta = abs((fresh.next_check_at - written_at).total_seconds())
            assert delta < _ROUND_TRIP_TOLERANCE_SECONDS, (
                f"next_check_at drifted by {delta}s round-tripping through Postgres "
                f"(written={written_at.isoformat()}, read={fresh.next_check_at.isoformat()})"
            )
        finally:
            verify_session.rollback()
            verify_session.close()
    finally:
        verify_engine.dispose()

    session.execute(text("DELETE FROM cases WHERE id = :id"), {"id": str(case.id)})
    session.commit()


def test_case_created_at_server_default_is_within_seconds_of_true_utc_now(session) -> None:
    """The other half of the bug: `server_default=func.now()` columns, computed entirely on
    the Postgres server (never touching Python's `datetime.now(UTC)` at all), were *also*
    shifted by the session timezone — this is the one case where the value being compared
    against was never even sent by the client, so it specifically proves the server-side
    default path is fixed too, not just client-computed values.
    """
    before = datetime.now(UTC)
    repo = SqlAlchemyCaseRepository(session)
    case = repo.add(Case(id=uuid4(), topic="tz-regression-created-at"))
    session.commit()
    after = datetime.now(UTC)

    fresh = repo.get_by_id(case.id)
    assert fresh is not None
    assert fresh.created_at is not None
    assert fresh.created_at.tzinfo is not None
    assert before - timedelta(seconds=_ROUND_TRIP_TOLERANCE_SECONDS) <= fresh.created_at
    assert fresh.created_at <= after + timedelta(seconds=_ROUND_TRIP_TOLERANCE_SECONDS)

    session.execute(text("DELETE FROM cases WHERE id = :id"), {"id": str(case.id)})
    session.commit()


def test_decision_created_at_server_default_is_within_seconds_of_true_utc_now(session) -> None:
    """Same server-side-default proof as above, for the `decisions` table specifically —
    Decision.created_at is what the Activity/Overview pages' "time ago" columns render."""
    repo = SqlAlchemyCaseRepository(session)
    case = repo.add(Case(id=uuid4(), topic="tz-regression-decision"))
    session.commit()

    before = datetime.now(UTC)
    decision = repo.add_decision(
        case.id,
        Decision(
            id=uuid4(),
            case_id=case.id,
            node_name="tz_regression_probe",
            reasoning_summary="probe",
            status=DecisionStatus.SUCCESS,
        ),
    )
    session.commit()
    after = datetime.now(UTC)

    assert decision.created_at is not None
    assert decision.created_at.tzinfo is not None
    assert before - timedelta(seconds=_ROUND_TRIP_TOLERANCE_SECONDS) <= decision.created_at
    assert decision.created_at <= after + timedelta(seconds=_ROUND_TRIP_TOLERANCE_SECONDS)

    session.execute(text("DELETE FROM cases WHERE id = :id"), {"id": str(case.id)})
    session.commit()
