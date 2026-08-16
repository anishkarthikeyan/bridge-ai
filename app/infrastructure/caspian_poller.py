"""Caspian inbound poller (Phase 6.6) — periodically drains pending events from the real
Caspian gateway so a live server can receive inbound messages without `caspian_sdk.CommClient
.listen()`'s blocking, unstoppable loop (see app/integrations/real_caspian_client.py's
docstring for why `listen()` doesn't fit a service that must shut down cleanly).

Mirrors app/infrastructure/scheduler.py's own shape deliberately (a single APScheduler job,
`max_instances=1`, clean start/shutdown) — same pattern, different trigger. Contains no
business logic of its own: `poll_once()` (RealCaspianClient) internally calls the ONE
registered handler for whatever it finds, and everything downstream of that (BridgeAgentHandler
-> ChannelAdapterRegistry -> IngestInboundMessageUseCase -> the LangGraph brain) is exactly the
same code path a real inbound webhook or `LocalCaspianClient.simulate_inbound()` already goes
through — this file never touches a Case, a Session, or the brain.

Only meaningful against `RealCaspianClient` — `LocalCaspianClient` delivers synchronously via
`simulate_inbound()` and needs no poller; app/main.py only constructs one of these when the
configured Caspian client actually exposes `poll_once`.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.infrastructure.config import Settings
from app.integrations.real_caspian_client import RealCaspianClient

logger = logging.getLogger(__name__)

_JOB_ID = "bridge-ai-caspian-inbound-poll"


class CaspianInboundPoller:
    def __init__(self, settings: Settings, caspian_client: RealCaspianClient) -> None:
        self._settings = settings
        self._caspian_client = caspian_client
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        self._scheduler.add_job(
            self._tick,
            "interval",
            seconds=self._settings.caspian_inbound_poll_interval_seconds,
            id=_JOB_ID,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "Caspian inbound poller started (interval=%ds).",
            self._settings.caspian_inbound_poll_interval_seconds,
        )

    def shutdown(self, wait: bool = True) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("Caspian inbound poller stopped.")

    def _tick(self) -> None:
        try:
            self._caspian_client.poll_once()
        except Exception:
            logger.exception("Caspian inbound poll failed — will retry next tick.")
