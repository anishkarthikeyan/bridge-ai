"""Live/demo verification support — test/demo infrastructure only, never imported by the
production app (app/main.py's lifespan wires the real scheduler poll loop independently of
this module) and never collected by pytest.

Fixes a real incident: a prior live cross-channel verification script waited up to 150s for
a real human's Telegram reply, then unconditionally deleted the Case and its LangGraph
checkpoint in a `finally` block regardless of whether the reply had actually arrived. The
real reply landed after the timeout, so by the time it arrived there was nothing left for it
to resume — the checkpoint mechanism was never at fault, the cleanup-on-timeout was.

The fix is procedural, not architectural: `wait_for_reply` below never deletes anything, on
timeout or otherwise. It reports a `WaitOutcome.status` of "REPLY_RECEIVED" or
"TIMEOUT_WAITING_FOR_REPLY" and always leaves the Case + checkpoint rows exactly as they are.
Cleanup is a separate, explicit, deliberately-named function (`cleanup_case`) that a human
calls only after actually inspecting the outcome — never automatically from a timeout branch.
Any live/demo script that waits on a real human reply should use these instead of open-coding
its own poll-then-delete loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.integrations.persistence.sqlalchemy.repositories.case_repository import (
        SqlAlchemyCaseRepository,
    )

REPLY_RECEIVED = "REPLY_RECEIVED"
TIMEOUT_WAITING_FOR_REPLY = "TIMEOUT_WAITING_FOR_REPLY"
CASE_MISSING = "CASE_MISSING"


@dataclass(frozen=True)
class WaitOutcome:
    status: str  # REPLY_RECEIVED | TIMEOUT_WAITING_FOR_REPLY | CASE_MISSING
    case_id: Any
    decisions_seen: int


def wait_for_reply(
    *,
    caspian_client: Any,
    session: Session,
    case_repository: SqlAlchemyCaseRepository,
    case_id: Any,
    decisions_before: int,
    timeout_seconds: float,
    poll_interval_seconds: float = 3.0,
    node_name: str = "receive_message",
) -> WaitOutcome:
    """Poll the real Caspian event stream for up to `timeout_seconds`, watching `case_id`
    for a new `node_name` decision (a real reply being processed). Never deletes or mutates
    the Case on any outcome, including timeout — that is the entire point of this helper.
    Report the result and let the caller (a human, inspecting output) decide what to do next.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        caspian_client.poll_once()
        session.commit()
        fresh = case_repository.get_by_id(case_id)
        if fresh is None:
            # Something else removed the Case out-of-band — stop and say so plainly rather
            # than guessing or treating it as a normal timeout.
            return WaitOutcome(status=CASE_MISSING, case_id=case_id, decisions_seen=decisions_before)
        if len(fresh.decisions) > decisions_before and any(
            d.node_name == node_name for d in fresh.decisions[decisions_before:]
        ):
            return WaitOutcome(
                status=REPLY_RECEIVED, case_id=case_id, decisions_seen=len(fresh.decisions)
            )
        time.sleep(poll_interval_seconds)
    return WaitOutcome(
        status=TIMEOUT_WAITING_FOR_REPLY, case_id=case_id, decisions_seen=decisions_before
    )


def cleanup_case(session: Session, case_id: Any) -> None:
    """Explicit, manual-only cleanup. Deletes the Case row and its LangGraph checkpoint rows
    (checkpoints/checkpoint_blobs/checkpoint_writes). Must be called deliberately, after a
    human has inspected the outcome — never wired to a timeout or any other automatic trigger.
    """
    session.rollback()
    session.execute(text("DELETE FROM cases WHERE id = :id"), {"id": str(case_id)})
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        session.execute(text(f"DELETE FROM {table} WHERE thread_id = :id"), {"id": str(case_id)})
    session.commit()
