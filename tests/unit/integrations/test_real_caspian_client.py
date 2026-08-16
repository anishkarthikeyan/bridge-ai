"""Unit tests for RealCaspianClient (Phase 6.6) — no real network calls; `caspian_sdk.CommClient`
is replaced with a small scripted fake (`_FakeCommClient`) recording every call, so the
translation/dispatch/continuity logic is exercised deterministically and fast. The real,
live `caspian-sdk` connection itself is covered separately by
tests/integration/test_caspian_live.py, which skips cleanly without credentials (Part 6.6
"TESTING": "Do not fake a live Caspian result and call it live").
"""

from __future__ import annotations

import pytest
from caspian_sdk import CommError, Message

from app.integrations import real_caspian_client as real_caspian_client_module
from app.integrations.real_caspian_client import RealCaspianClient


def _patch_confirmation_timing(*, fast: bool) -> tuple[float, float]:
    """Shrinks _await_conversation_id's bounded wait for a test that must let it actually
    time out — these are plain module globals, not settings, so they're restored by hand
    rather than via pytest's monkeypatch fixture (no fixture wiring needed for two lines)."""
    original = (
        real_caspian_client_module._SEND_CONFIRMATION_TIMEOUT_SECONDS,
        real_caspian_client_module._SEND_CONFIRMATION_POLL_INTERVAL_SECONDS,
    )
    if fast:
        real_caspian_client_module._SEND_CONFIRMATION_TIMEOUT_SECONDS = 0.05
        real_caspian_client_module._SEND_CONFIRMATION_POLL_INTERVAL_SECONDS = 0.01
    return original


def _restore_confirmation_timing(timeout: float, interval: float) -> None:
    real_caspian_client_module._SEND_CONFIRMATION_TIMEOUT_SECONDS = timeout
    real_caspian_client_module._SEND_CONFIRMATION_POLL_INTERVAL_SECONDS = interval


class _FakeCommClient:
    """Records every call; scripted return values per method, settable per test."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.on_message_handler = None
        self.connect_email_result: dict = {
            "id": "conn-email-1",
            "address": "bridge@agents.example.com",
            "status": "active",
        }
        self.connect_telegram_result: dict = {"id": "conn-tg-1", "status": "active"}
        self.list_connections_result: dict[str, list[dict]] = {}
        self.list_conversations_result: dict[str, list[dict]] = {}
        """connection_id -> conversations, for _find_existing_conversation's discovery scan."""
        self.list_messages_result: dict[str, list[dict]] = {}
        """conversation_id -> messages, for the same scan."""
        self.initiate_result: dict = {"id": "out-msg-1", "conversation_id": "conv-new-1"}
        self.send_message_result: dict = {"id": "out-msg-2"}
        self.dispatch_pending_result: int = 0
        self.events_result: list[dict] = []
        self.message_sent_events: list[dict] = []
        self.raise_on: dict[str, Exception] = {}

    def _record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))
        if name in self.raise_on:
            raise self.raise_on[name]

    def on_message(self, handler):
        self._record("on_message", handler)
        self.on_message_handler = handler
        return handler

    def connect_email(self, **kwargs):
        self._record("connect_email", **kwargs)
        return self.connect_email_result

    def connect_telegram(self, bot_token, **kwargs):
        self._record("connect_telegram", bot_token, **kwargs)
        return self.connect_telegram_result

    def list_connections(self, channel=None):
        self._record("list_connections", channel=channel)
        # Mirrors a confirmed real-gateway quirk (Phase 6.6 live verification): the real
        # Caspian API's channel= filter is NOT applied server-side — it returns every
        # connection regardless of what was requested. RealCaspianClient must filter
        # client-side; this fake ignores `channel` on purpose so a regression there fails
        # the tests below instead of only showing up live. Each connection's "channel" key
        # defaults to whichever list_connections_result key it was stored under, so existing
        # test fixtures that predate this don't need to repeat it explicitly.
        return [
            {**c, "channel": c.get("channel", key)}
            for key, connections in self.list_connections_result.items()
            for c in connections
        ]

    def list_conversations(self, connection_id=None):
        self._record("list_conversations", connection_id=connection_id)
        return self.list_conversations_result.get(connection_id, [])

    def list_messages(self, conversation_id):
        self._record("list_messages", conversation_id)
        return self.list_messages_result.get(conversation_id, [])

    def initiate(self, connection_id, recipient, text):
        self._record(
            "initiate", connection_id, recipient=recipient, text=text
        )  # raises if scripted
        return self.initiate_result

    def send_message(self, conversation_id, text=None, **kwargs):
        self._record("send_message", conversation_id, text=text, **kwargs)
        return self.send_message_result

    def dispatch_pending(self, after_seq=0):
        self._record("dispatch_pending", after_seq=after_seq)
        return self.dispatch_pending_result

    def events(self, after_seq=0, limit=100, type=None):
        self._record("events", after_seq=after_seq, limit=limit, type=type)
        # Untyped calls (from _current_latest_seq's backlog scan) and type="message.sent"
        # calls (from _await_conversation_id's send-confirmation poll) are tracked
        # separately, each returning its own configured result on its first call only, empty
        # after — enough for both callers' paging loops to terminate deterministically.
        matching_calls = [c for c in self.calls if c[0] == "events" and c[2].get("type") == type]
        if len(matching_calls) != 1:
            return []
        return self.message_sent_events if type == "message.sent" else self.events_result

    def close(self):
        self._record("close")


def _message(**overrides) -> Message:
    defaults = {
        "id": "msg-1",
        "conversation_id": "conv-1",
        "connection_id": "conn-email-1",
        "customer_id": "cust-1",
        "agent_id": "agent-1",
        "channel": "email",
        "sender": {"name": "Dana Kapoor", "email": "dana@co.com"},
        "subject": "Changing the refund flow",
        "text": "Wanted Finance looped in.",
        "html": None,
        "_client": None,
        "media": [],
        "chat_type": None,
    }
    defaults.update(overrides)
    return Message(**defaults)


def _client_with(comm: _FakeCommClient) -> RealCaspianClient:
    return RealCaspianClient(comm)


# --- one-handler rule (Part "ONE HANDLER PROOF" / testing item 2 & 8) ----------------------


def test_register_handler_registers_exactly_one_on_message_callback() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)

    client.register_handler(lambda channel, payload: None)

    on_message_calls = [c for c in comm.calls if c[0] == "on_message"]
    assert len(on_message_calls) == 1


def test_registering_a_second_handler_raises() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    client.register_handler(lambda channel, payload: None)

    with pytest.raises(RuntimeError, match="only one Caspian handler"):
        client.register_handler(lambda channel, payload: None)


# --- inbound: email and telegram both reach the SAME handler (testing items 3 & 4) ---------


def test_inbound_email_message_translates_and_reaches_the_registered_handler() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    received: list[tuple[str, dict]] = []
    client.register_handler(lambda channel, payload: received.append((channel, payload)))

    client._on_message(
        _message(channel="email", sender={"name": "Dana Kapoor", "email": "dana@co.com"})
    )

    assert len(received) == 1
    channel, payload = received[0]
    assert channel == "email"
    assert payload["from"] == {
        "name": "Dana Kapoor",
        "email": "dana@co.com",
        "telegram_handle": None,
        "role": None,
    }
    assert payload["body"] == "Wanted Finance looped in."
    assert payload["thread_ref"] == "conv-1"
    assert payload["message_ref"] == "msg-1"


def test_inbound_telegram_message_reaches_the_same_handler_as_email() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    received: list[tuple[str, dict]] = []
    same_handler = lambda channel, payload: received.append((channel, payload))  # noqa: E731
    client.register_handler(same_handler)

    client._on_message(_message(channel="email", sender={"name": "Dana", "email": "dana@co.com"}))
    client._on_message(
        _message(
            id="msg-2",
            conversation_id="conv-2",
            channel="telegram",
            sender={"name": "Alice", "handle": "@alice"},
            subject=None,
            text="On it.",
        )
    )

    assert [c for c, _ in received] == ["email", "telegram"]
    telegram_payload = received[1][1]
    assert telegram_payload["from"] == {
        "name": "Alice",
        "email": None,
        "telegram_handle": "@alice",
        "role": None,
    }


def test_inbound_email_uses_the_real_sender_shape_with_address_key() -> None:
    """Regression test for a confirmed real-gateway sender shape (Phase 6.6.7 live
    investigation): a real inbound email's sender is `{"address": "...", "name": ...}` — NOT
    `{"email": "...", ...}` as originally guessed (flagged unverified in the Phase 6.6
    report). Exact shape observed live: {'address': 'tester@agents.trycaspianai.com',
    'name': None}."""
    comm = _FakeCommClient()
    client = _client_with(comm)
    received: list[tuple[str, dict]] = []
    client.register_handler(lambda channel, payload: received.append((channel, payload)))

    client._on_message(
        _message(
            channel="email", sender={"address": "tester@agents.trycaspianai.com", "name": None}
        )
    )

    _, payload = received[0]
    assert payload["from"]["email"] == "tester@agents.trycaspianai.com"
    assert payload["from"]["name"] == "tester@agents.trycaspianai.com"  # no real name given either


def test_inbound_telegram_uses_the_real_sender_shape_with_address_key() -> None:
    """Same regression, for Telegram — exact shape observed live from a real /start + "hi":
    {'address': '8786421311', 'name': 'Anish Karthikeyan'} (a numeric Telegram user id, not a
    "handle"/"username" key)."""
    comm = _FakeCommClient()
    client = _client_with(comm)
    received: list[tuple[str, dict]] = []
    client.register_handler(lambda channel, payload: received.append((channel, payload)))

    client._on_message(
        _message(
            channel="telegram",
            sender={"address": "8786421311", "name": "Anish Karthikeyan"},
            subject=None,
            text="hi",
        )
    )

    _, payload = received[0]
    assert payload["from"]["telegram_handle"] == "8786421311"
    assert payload["from"]["name"] == "Anish Karthikeyan"
    assert payload["from"]["email"] is None


def test_inbound_message_with_no_handler_registered_does_not_raise() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    client._on_message(_message())  # no register_handler() call — must not raise


def test_inbound_message_caches_conversation_id_for_the_sender() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    client.register_handler(lambda channel, payload: None)

    client._on_message(
        _message(
            channel="email",
            conversation_id="conv-77",
            sender={"name": "Dana", "email": "dana@co.com"},
        )
    )

    assert client._conversations[("email", "dana@co.com")] == "conv-77"


# --- outbound (testing items 5 & 6) ---------------------------------------------------------


def test_send_initiates_a_new_conversation_when_none_is_known() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    client._connections["email"] = "conn-email-1"

    result = client.send("email", "john@co.com", {"body": "Please review."})

    assert result.success is True
    assert result.external_message_ref == "out-msg-1"
    initiate_calls = [c for c in comm.calls if c[0] == "initiate"]
    assert len(initiate_calls) == 1
    _, args, kwargs = initiate_calls[0]
    assert args == ("conn-email-1",)
    assert kwargs == {"recipient": "john@co.com", "text": "Please review."}
    # The new conversation is now cached for continuity (Phase 6.6 "THREAD CONTINUITY").
    assert client._conversations[("email", "john@co.com")] == "conv-new-1"


def test_send_reuses_a_pre_existing_conversation_discovered_via_list_conversations() -> None:
    """Regression test for a confirmed real-gateway behavior (Phase 6.6.7 live verification):
    Telegram's initiate() 422s with "Connection does not grant 'initiate'" — a bot can only
    continue a chat the other side started. A recipient who already has a conversation with
    us (e.g. from messaging the bot before this process started) must be discovered via
    list_conversations()/list_messages() and reached with send_message(), never initiate()."""
    comm = _FakeCommClient()
    comm.list_conversations_result["conn-tg-1"] = [
        {"id": "conv-existing-telegram", "connection_id": "conn-tg-1"}
    ]
    comm.list_messages_result["conv-existing-telegram"] = [
        {"sender": {"address": "8786421311", "name": "Real User"}, "recipients": []}
    ]
    comm.send_message_result = {"id": "out-msg-9", "conversation_id": "conv-existing-telegram"}
    client = _client_with(comm)
    client._connections["telegram"] = "conn-tg-1"

    result = client.send("telegram", "8786421311", {"body": "Please review."})

    assert result.success is True
    assert result.conversation_ref == "conv-existing-telegram"
    assert not [c for c in comm.calls if c[0] == "initiate"]  # never even attempted
    send_message_calls = [c for c in comm.calls if c[0] == "send_message"]
    assert len(send_message_calls) == 1
    assert send_message_calls[0][1] == ("conv-existing-telegram",)


def test_send_falls_back_to_initiate_when_no_existing_conversation_is_found() -> None:
    comm = _FakeCommClient()
    comm.list_conversations_result["conn-email-1"] = []  # nothing to discover
    client = _client_with(comm)
    client._connections["email"] = "conn-email-1"

    result = client.send("email", "new-person@co.com", {"body": "hi"})

    assert result.success is True
    assert [c for c in comm.calls if c[0] == "initiate"]  # cold-start really was attempted
    assert [c for c in comm.calls if c[0] == "list_conversations"]  # discovery was tried first


def test_send_via_cold_initiate_waits_for_the_async_message_sent_confirmation() -> None:
    """Regression test for a confirmed real-gateway behavior (Phase 6.6.6 live
    investigation): initiate()'s synchronous response never carries a conversation id — only
    {"connection_id", "recipient", "status": "queued"} — because the send is asynchronous.
    The real conversation id only becomes available via a later `message.sent` event."""
    comm = _FakeCommClient()
    comm.initiate_result = {
        "connection_id": "conn-email-1",
        "recipient": "john@co.com",
        "status": "queued",
    }
    comm.message_sent_events = [
        {
            "seq": 501,
            "type": "message.sent",
            "data": {
                "message": {
                    "id": "msg-confirmed-1",
                    "conversation_id": "conv-confirmed-1",
                    "connection_id": "conn-email-1",
                    "direction": "outbound",
                    "recipients": [{"address": "john@co.com"}],
                }
            },
        }
    ]
    client = _client_with(comm)
    client._connections["email"] = "conn-email-1"

    result = client.send("email", "john@co.com", {"body": "Please review."})

    assert result.success is True
    assert result.conversation_ref == "conv-confirmed-1"
    assert client._conversations[("email", "john@co.com")] == "conv-confirmed-1"


def test_send_via_cold_initiate_ignores_a_message_sent_event_for_a_different_recipient() -> None:
    comm = _FakeCommClient()
    comm.initiate_result = {
        "connection_id": "conn-email-1",
        "recipient": "john@co.com",
        "status": "queued",
    }
    comm.message_sent_events = [
        {
            "seq": 501,
            "type": "message.sent",
            "data": {
                "message": {
                    "id": "msg-other",
                    "conversation_id": "conv-someone-else",
                    "connection_id": "conn-email-1",
                    "direction": "outbound",
                    "recipients": [{"address": "someone-else@co.com"}],
                }
            },
        }
    ]
    client = _client_with(comm)
    client._connections["email"] = "conn-email-1"
    original_timeout, original_interval = _patch_confirmation_timing(fast=True)
    try:
        result = client.send("email", "john@co.com", {"body": "Please review."})
    finally:
        _restore_confirmation_timing(original_timeout, original_interval)

    assert result.success is True  # the send itself still succeeded
    assert result.conversation_ref is None  # never fabricated from someone else's event
    assert ("email", "john@co.com") not in client._conversations


def test_send_via_cold_initiate_times_out_gracefully_when_never_confirmed() -> None:
    comm = _FakeCommClient()
    comm.initiate_result = {
        "connection_id": "conn-email-1",
        "recipient": "john@co.com",
        "status": "queued",
    }
    client = _client_with(comm)
    client._connections["email"] = "conn-email-1"

    original_timeout, original_interval = _patch_confirmation_timing(fast=True)
    try:
        result = client.send("email", "john@co.com", {"body": "Please review."})
    finally:
        _restore_confirmation_timing(original_timeout, original_interval)

    assert result.success is True  # Caspian accepted the send — that's what SUCCESS tracks
    assert result.conversation_ref is None  # honestly reports "couldn't confirm", never fakes it


def test_send_continues_an_existing_conversation_instead_of_re_initiating() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    client._connections["email"] = "conn-email-1"
    client._conversations[("email", "john@co.com")] = "conv-existing-9"

    result = client.send("email", "john@co.com", {"body": "Following up."})

    assert result.success is True
    assert result.external_message_ref == "out-msg-2"
    assert not [c for c in comm.calls if c[0] == "initiate"]
    send_message_calls = [c for c in comm.calls if c[0] == "send_message"]
    assert len(send_message_calls) == 1
    _, args, kwargs = send_message_calls[0]
    assert args == ("conv-existing-9",)
    assert kwargs["text"] == "Following up."


def test_send_accepts_telegram_wire_format_key_too() -> None:
    """TelegramAdapter's outbound wire format uses "text", not "body" (see
    telegram_adapter.py) — send() must handle both."""
    comm = _FakeCommClient()
    client = _client_with(comm)
    client._connections["telegram"] = "conn-tg-1"

    result = client.send("telegram", "@alice", {"chat_id": "@alice", "text": "Approved?"})

    assert result.success is True
    _, args, kwargs = [c for c in comm.calls if c[0] == "initiate"][0]
    assert kwargs["text"] == "Approved?"


def test_send_fails_gracefully_when_channel_never_connected() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)  # no provision() called — no connections at all

    result = client.send("telegram", "@alice", {"body": "hi"})

    assert result.success is False
    assert "telegram" in result.error
    assert not comm.calls  # never even attempted a Caspian call


def test_send_failure_is_reported_without_raising() -> None:
    comm = _FakeCommClient()
    comm.raise_on["initiate"] = CommError(500, "gateway hiccup")
    client = _client_with(comm)
    client._connections["email"] = "conn-email-1"

    result = client.send("email", "john@co.com", {"body": "hi"})

    assert result.success is False
    assert "gateway hiccup" in result.error


# --- provisioning (Part "Channel Requirement": actually connect the channels) --------------


def test_provision_creates_a_new_email_connection_when_none_exists() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)

    connections = client.provision(email_username="bridge-ai", telegram_bot_token=None)

    assert connections["email"] == "conn-email-1"
    connect_calls = [c for c in comm.calls if c[0] == "connect_email"]
    assert len(connect_calls) == 1
    assert connect_calls[0][2]["username"] == "bridge-ai"


def test_provision_reuses_an_already_active_connection_instead_of_duplicating() -> None:
    comm = _FakeCommClient()
    comm.list_connections_result["email"] = [{"id": "conn-existing", "status": "active"}]
    client = _client_with(comm)

    connections = client.provision(email_username=None, telegram_bot_token=None)

    assert connections["email"] == "conn-existing"
    assert not [c for c in comm.calls if c[0] == "connect_email"]


def test_provision_reuses_a_non_active_connection_rather_than_creating_a_duplicate() -> None:
    comm = _FakeCommClient()
    comm.list_connections_result["email"] = [{"id": "conn-provisioning", "status": "provisioning"}]
    client = _client_with(comm)

    connections = client.provision(email_username=None, telegram_bot_token=None)

    assert connections["email"] == "conn-provisioning"
    assert not [c for c in comm.calls if c[0] == "connect_email"]


def test_provision_discovers_an_existing_telegram_connection_without_a_local_bot_token() -> None:
    """The actual fix this test proves: a Telegram connection Caspian already owns (e.g.
    created once via `caspian-cli`, entirely outside this process) must be discovered and
    reused via list_connections() even when this deployment has no TELEGRAM_BOT_TOKEN of its
    own — the token is only needed to *create* a connection that doesn't exist yet, never to
    rediscover one that does."""
    comm = _FakeCommClient()
    comm.list_connections_result["telegram"] = [{"id": "conn-tg-existing", "status": "active"}]
    client = _client_with(comm)

    connections = client.provision(email_username=None, telegram_bot_token=None)

    assert connections["telegram"] == "conn-tg-existing"
    assert not [c for c in comm.calls if c[0] == "connect_telegram"]


def test_provision_cannot_create_telegram_without_a_bot_token_or_an_existing_connection() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)  # no existing telegram connection, no bot token

    connections = client.provision(email_username=None, telegram_bot_token=None)

    assert "telegram" not in connections
    assert not [c for c in comm.calls if c[0] == "connect_telegram"]
    # Discovery was still attempted (Part 7's point: no manual token duplication required to
    # *try* reusing what Caspian already owns) — it just found nothing to reuse this time.
    assert [c for c in comm.calls if c[0] == "list_connections" and c[2]["channel"] == "telegram"]


def test_provision_connects_telegram_when_bot_token_is_configured() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)

    connections = client.provision(email_username=None, telegram_bot_token="123:ABC")

    assert connections["telegram"] == "conn-tg-1"
    connect_calls = [c for c in comm.calls if c[0] == "connect_telegram"]
    assert len(connect_calls) == 1
    assert connect_calls[0][1] == ("123:ABC",)


def test_provision_connects_both_email_and_telegram_channels() -> None:
    """Part "Channel Requirement": at least two real Caspian channels, actually connected."""
    comm = _FakeCommClient()
    client = _client_with(comm)

    connections = client.provision(email_username="bridge-ai", telegram_bot_token="123:ABC")

    assert set(connections.keys()) == {"email", "telegram"}


def test_provision_assigns_the_right_connection_to_the_right_channel_when_the_gateway_returns_both() -> (
    None
):
    """Regression test for a confirmed real-gateway quirk (Phase 6.6 live verification):
    list_connections(channel=...) returns every connection regardless of the filter — see
    _FakeCommClient.list_connections. Without client-side filtering, provision() picked the
    first *active* connection in that unfiltered list for BOTH channels — silently assigning
    the email connection's id to "telegram" too.
    """
    comm = _FakeCommClient()
    comm.list_connections_result["email"] = [
        {"id": "conn-email-real", "channel": "email", "status": "active"}
    ]
    comm.list_connections_result["telegram"] = [
        {"id": "conn-tg-real", "channel": "telegram", "status": "active"}
    ]
    client = _client_with(comm)

    connections = client.provision(email_username=None, telegram_bot_token=None)

    assert connections["email"] == "conn-email-real"
    assert connections["telegram"] == "conn-tg-real"
    assert connections["email"] != connections["telegram"]


# --- inbound polling -------------------------------------------------------------------------


def test_poll_once_advances_the_cursor_across_calls() -> None:
    comm = _FakeCommClient()
    client = _client_with(comm)
    comm.dispatch_pending_result = 42

    first = client.poll_once()

    assert first == 42
    comm.dispatch_pending_result = 99
    second = client.poll_once()

    assert second == 99
    calls = [c for c in comm.calls if c[0] == "dispatch_pending"]
    assert calls[0][2]["after_seq"] == 0
    assert calls[1][2]["after_seq"] == 42


def test_register_handler_skips_existing_backlog_instead_of_replaying_it() -> None:
    """Regression test for a confirmed real-gateway behavior (Phase 6.6.5 live verification):
    a fresh RealCaspianClient with no cursor established would call
    dispatch_pending(after_seq=0) on its first poll and replay this Caspian project's entire
    event history — every message ever received, including from long before this process
    started. register_handler() must establish "now" as the starting point, using only
    events() (dispatch_pending has no such default of its own, unlike client.listen())."""
    comm = _FakeCommClient()
    comm.events_result = [{"seq": 100}, {"seq": 250}]  # simulates old backlog already present
    client = _client_with(comm)

    client.register_handler(lambda channel, payload: None)
    client.poll_once()

    dispatch_calls = [c for c in comm.calls if c[0] == "dispatch_pending"]
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0][2]["after_seq"] == 250  # starts after the backlog, not at 0
