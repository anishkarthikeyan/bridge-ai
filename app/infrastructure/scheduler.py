"""Follow-up sweep scheduler — a single in-process APScheduler job (a distributed queue is
Future Work; see architecture doc §1). Registers RunFollowupSweepUseCase (Phase 6.5 Part 8)
on an interval; this class is intentionally thin, containing no business rules of its own —
"periodically wake up -> find cases that are due -> invoke the existing application/domain
workflow" happens entirely inside RunFollowupSweepUseCase/EvaluateCaseUseCase. This file only
owns the timer and each tick's unit-of-work lifecycle (a short-lived Session, committed or
rolled back once per tick).

Duplicate-dispatch prevention (Part 8, "Scheduler Safety") is layered, not reinvented here:
  - within one process, `max_instances=1` + `coalesce=True` mean a slow tick can never overlap
    with the next one;
  - across processes, `CaseRepositoryPort.list_due_for_followup`'s `SELECT ... FOR UPDATE
    SKIP LOCKED` (app/integrations/persistence/sqlalchemy/repositories/case_repository.py)
    means two processes' ticks never claim the same case at once.
Both are standard, minimal mechanisms appropriate for a hackathon MVP — not a new
distributed-systems architecture.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from app.application.use_cases.evaluate_case import EvaluateCaseUseCase
from app.application.use_cases.run_followup_sweep import RunFollowupSweepUseCase
from app.infrastructure.config import Settings
from app.infrastructure.di_container import (
    Container,
    build_case_repository,
    build_dispatch_use_case,
)

logger = logging.getLogger(__name__)

_JOB_ID = "bridge-ai-followup-sweep"


class FollowupScheduler:
    def __init__(
        self,
        settings: Settings,
        container: Container,
        session_factory: Callable[[], Session],
        compiled_graph: CompiledStateGraph | None = None,
    ) -> None:
        self._settings = settings
        self._container = container
        self._session_factory = session_factory
        self._compiled_graph = compiled_graph
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        if not self._settings.scheduler_enabled:
            logger.info(
                "Follow-up scheduler disabled (SCHEDULER_ENABLED=false) — autonomous "
                "follow-up will not run; cases will still respond to real replies."
            )
            return

        self._scheduler.add_job(
            self._tick,
            "interval",
            seconds=self._settings.scheduler_interval_seconds,
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "Follow-up scheduler started (interval=%ds).", self._settings.scheduler_interval_seconds
        )

    def shutdown(self, wait: bool = True) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("Follow-up scheduler stopped.")

    def _tick(self) -> None:
        """One unit of work: open a Session, run the sweep, commit, always close — never
        leaks a connection back to the pool even if the sweep raises (Part 9)."""
        session = self._session_factory()
        try:
            case_repository = build_case_repository(session)
            dispatch_use_case = build_dispatch_use_case(self._container, case_repository)
            evaluate_case_use_case = EvaluateCaseUseCase(
                case_repository,
                self._container.llm_client,
                dispatch_use_case,
                policy_loader=self._container.policy_loader,
                channel_registry=self._container.channel_registry,
                role_resolver=self._container.role_resolver,
                role_directory=self._container.role_directory,
                compiled_graph=self._compiled_graph,
            )
            RunFollowupSweepUseCase(case_repository, evaluate_case_use_case).run()
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Follow-up sweep tick failed — rolled back; will retry next tick.")
        finally:
            session.close()
