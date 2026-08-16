"""Live Caspian integration test (Phase 6.6 "LIVE VERIFICATION") — the one place in this
suite that talks to the real Caspian gateway with real credentials, mirroring
tests/integration/test_featherless_live.py's own pattern exactly. Skips cleanly (not as a
failure) when `CASPIAN_API_KEY` isn't configured — every other Caspian test in this suite
(tests/unit/integrations/test_real_caspian_client.py,
tests/integration/test_caspian_real_client_routing.py) runs against a scripted fake
`caspian_sdk.CommClient` and never depends on this file or on real credentials.

Uses `caspian_sdk`'s own `test_email()` helper — built into the SDK specifically to inject a
real inbound event without needing an actual external sender — rather than requiring a human
to send a real email during a test run. Telegram inbound has no equivalent synthetic-injection
helper in the SDK, so this file only proves live inbound for email; Telegram is proven live by
manual verification instead (see the Phase 6.6 report's "Real Caspian verification result").

Environment note (honest, per Part "TESTING": "Do not fake a live Caspian result and call it
live"): CASPIAN_API_KEY was NOT configured in the environment this was written and run in, so
every test below was written against the real, installed `caspian-sdk`'s documented API but
could only be verified to *skip cleanly*, not to pass live. See the Phase 6.6 report.
"""

from __future__ import annotations

import time

import pytest
from caspian_sdk import CommClient

from app.infrastructure.config import get_settings
from app.integrations.real_caspian_client import RealCaspianClient

pytestmark = pytest.mark.skipif(
    not get_settings().caspian_api_key,
    reason="CASPIAN_API_KEY not configured — skipping live Caspian integration test",
)


@pytest.fixture(scope="module")
def real_client() -> RealCaspianClient:
    settings = get_settings()
    comm_client = CommClient(
        api_key=settings.caspian_api_key, base_url=settings.caspian_base_url or None
    )
    return RealCaspianClient(comm_client)


def test_real_caspian_client_authenticates(real_client: RealCaspianClient) -> None:
    """A successful call to any authenticated endpoint proves the API key is valid — Part
    18-equivalent for Caspian: "Verify the real Caspian client can authenticate."""
    channels = real_client._client.channels()
    assert isinstance(channels, list)


def test_provision_connects_email_for_real(real_client: RealCaspianClient) -> None:
    settings = get_settings()
    connections = real_client.provision(
        email_username=settings.caspian_email_username or None, telegram_bot_token=None
    )
    assert "email" in connections
    assert connections["email"]


def test_provision_discovers_or_connects_telegram_for_real(real_client: RealCaspianClient) -> None:
    """No TELEGRAM_BOT_TOKEN needs to be configured locally when Caspian already owns the
    connection (e.g. made once via `caspian-cli`, outside this process) — provision() must
    discover and reuse it via list_connections() alone. A bot token is only a fallback for
    creating a connection that doesn't exist yet, so this test intentionally passes none.
    """
    connections = real_client.provision(email_username=None, telegram_bot_token=None)
    assert "telegram" in connections, (
        "no telegram connection was discovered or created — either connect one via "
        "caspian-cli, or set TELEGRAM_BOT_TOKEN so provision() can create one"
    )
    assert connections["telegram"]


def test_real_inbound_email_reaches_the_registered_handler(real_client: RealCaspianClient) -> None:
    """Demonstrates: real Caspian test_email() -> real CommClient event stream ->
    RealCaspianClient.poll_once() -> the ONE registered handler — end to end, with a real
    gateway round trip, no fake CommClient involved.
    """
    email_connection_id = real_client._connections.get("email")
    assert email_connection_id, (
        "email must be provisioned first (test_provision_connects_email_for_real)"
    )

    received: list[tuple[str, dict]] = []
    real_client.register_handler(lambda channel, payload: received.append((channel, payload)))

    # connection_id is passed explicitly — omitting it left the gateway free to pick whichever
    # connection it treats as default, which was observed to be the telegram one (test_email
    # is email-only and 422s against a non-email connection).
    real_client._client.test_email(
        text="Bridge AI Phase 6.6 live verification.",
        subject="Bridge AI live test",
        connection_id=email_connection_id,
    )

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and not received:
        real_client.poll_once()
        if not received:
            time.sleep(2.0)

    assert received, "no inbound event arrived within 30s of test_email()"
    channel, payload = received[0]
    assert channel == "email"
    assert payload["body"]
