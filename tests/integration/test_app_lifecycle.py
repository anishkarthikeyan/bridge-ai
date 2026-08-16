"""FastAPI startup/shutdown lifecycle tests (Phase 6.5 Parts 9/15) — against a real Postgres,
the same DATABASE_URL the app itself uses (`with TestClient(app) as client:` is what actually
triggers `lifespan()`; see app/main.py's docstring for why a plain `TestClient(app)` does not
and therefore doesn't need a database — that's what every other, DB-free test in this suite
already relies on). Skips cleanly if that database isn't reachable, rather than failing
unrelated tests, matching the same philosophy as the live Featherless test.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.infrastructure.config import get_settings
from app.main import create_app


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
    not _database_reachable(),
    reason="Postgres not reachable at DATABASE_URL — skipping app lifecycle test",
)


def test_app_starts_cleanly_and_wires_every_lifespan_component() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        assert app.state.compiled_graph is not None
        assert app.state.scheduler is not None
        assert app.state.bridge_agent_handler is not None


def test_scheduler_starts_with_the_app_and_stops_on_shutdown() -> None:
    app = create_app()
    with TestClient(app):
        assert app.state.scheduler._scheduler.running is True
    assert app.state.scheduler._scheduler.running is False


def test_app_enforces_exactly_one_caspian_handler() -> None:
    app = create_app()
    with TestClient(app):
        caspian_client = app.state.container.caspian_client
        # LocalCaspianClient.register_handler raises on a second registration — the
        # structural enforcement of "exactly one Caspian handler" (architecture doc §9),
        # already exercised once by lifespan() itself registering the first (and only) one.
        with pytest.raises(RuntimeError, match="only one Caspian handler"):
            caspian_client.register_handler(lambda channel, payload: None)


def test_cases_api_works_end_to_end_once_the_app_is_fully_started() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/cases")
        assert response.status_code == 200
        assert "items" in response.json()
