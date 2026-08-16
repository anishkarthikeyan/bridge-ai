"""Application entrypoint.

`create_app()` is the FastAPI app factory. It stays deliberately cheap and DB-free — Settings,
logging, and the DI container (Container has no I/O of its own: it loads two local YAML files
and constructs a FeatherlessClient object, which does not touch the network until a method is
called) — so constructing the app (e.g. `TestClient(create_app())`, as every existing test's
`client` fixture already does) never requires a live Postgres connection.

Everything that DOES need a live database — the LangGraph Postgres checkpointer, the
process-lifetime Session the brain and the scheduler share, the compiled graph, the one
Caspian handler registration, and the follow-up scheduler — is wired in `lifespan()` instead
(Part 9's checklist, items 3/8/9/10 beyond what `build_container()` already covers). Lifespan
only runs when the app is actually served (`uv run bridge-ai` / `uvicorn ...`) or when a test
opts in with `with TestClient(app) as client:` — a plain `TestClient(app)` never triggers it
(verified against the installed Starlette version during this build), which is exactly why
adding real database startup here does not break `tests/integration/test_health.py` or any
other existing Phase 6 test that only ever constructs `TestClient(create_app())` directly.

Run locally with `uv run bridge-ai`, or directly with `uvicorn app.main:app --reload`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.use_cases.ingest_inbound_message import IngestInboundMessageUseCase
from app.brain.checkpointer import postgres_checkpointer
from app.infrastructure.caspian_poller import CaspianInboundPoller
from app.infrastructure.config import get_settings
from app.infrastructure.db import SessionLocal
from app.infrastructure.di_container import (
    Container,
    build_case_repository,
    build_compiled_graph,
    build_container,
)
from app.infrastructure.logging import configure_logging
from app.infrastructure.scheduler import FollowupScheduler
from app.integrations.api.routers import cases, dashboard, health
from app.integrations.inbound.caspian_handler import BridgeAgentHandler
from app.integrations.real_caspian_client import RealCaspianClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Part 9's remaining startup steps (checkpointer through scheduler) and their clean
    shutdown, in reverse order: stop the scheduler first (so no tick is mid-sweep against a
    session that's about to close), then close the process-lifetime Session, then close the
    checkpointer's Postgres connection last.
    """
    settings = get_settings()
    container: Container = app.state.container

    with postgres_checkpointer(settings.database_url) as checkpointer, SessionLocal() as session:
        case_repository = build_case_repository(session)
        compiled_graph = build_compiled_graph(
            container, case_repository, container.llm_client, checkpointer
        )

        inbound_router = IngestInboundMessageUseCase(case_repository, compiled_graph)
        # Registered exactly once, here — the one-Caspian-handler rule (architecture doc §9)
        # is enforced structurally by both CaspianClientProtocol implementations raising if
        # called twice (LocalCaspianClient and RealCaspianClient alike); this is the only
        # call site, regardless of which one Container is holding (Phase 6.6).
        handler = BridgeAgentHandler(container.channel_adapter_registry, inbound_router)
        container.caspian_client.register_handler(handler)

        scheduler = FollowupScheduler(settings, container, SessionLocal, compiled_graph)
        scheduler.start()

        # Phase 6.6: only meaningful for the real SDK — LocalCaspianClient delivers
        # synchronously via simulate_inbound() and has no channels to connect or events to
        # poll. `provision()` actually connects email + telegram (Part "Channel Requirement":
        # "Do not merely instantiate adapters. Actually connect the channels."); the poller
        # then periodically drains inbound events into the one handler just registered above.
        caspian_poller: CaspianInboundPoller | None = None
        if isinstance(container.caspian_client, RealCaspianClient):
            connections = container.caspian_client.provision(
                email_username=settings.caspian_email_username or None,
                telegram_bot_token=settings.telegram_bot_token or None,
            )
            logger.info("Caspian channels connected: %s", list(connections.keys()))
            caspian_poller = CaspianInboundPoller(settings, container.caspian_client)
            caspian_poller.start()

        app.state.compiled_graph = compiled_graph
        app.state.bridge_agent_handler = handler
        app.state.scheduler = scheduler
        app.state.caspian_poller = caspian_poller

        logger.info("Bridge AI fully started (env=%s).", settings.app_env)
        try:
            yield
        finally:
            if caspian_poller is not None:
                caspian_poller.shutdown(wait=True)
            scheduler.shutdown(wait=True)
            logger.info("Bridge AI shutting down.")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    container = build_container()

    app = FastAPI(
        title="Bridge AI",
        description="Autonomous, multi-channel communication agent — backend.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.container = container

    app.include_router(health.router)
    app.include_router(cases.router)
    app.include_router(dashboard.router)

    _register_error_handlers(app)

    logger.info("Bridge AI starting (env=%s)", settings.app_env)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Part 13: 400 for invalid request parameters, 500 for unexpected internal failures,
    neither ever leaking a stack trace or a secret to the client. 404 needs no handler here —
    every read endpoint raises `HTTPException(404, ...)` directly (app/integrations/api/routers/
    cases.py), and FastAPI's own default HTTPException handling already renders that correctly
    (verified: registering the catch-all Exception handler below does not shadow it).
    """

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception while processing %s %s", request.method, request.url.path
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app = create_app()


def run() -> None:
    """Console-script entrypoint — `uv run bridge-ai`."""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.is_local,
    )


if __name__ == "__main__":
    run()
