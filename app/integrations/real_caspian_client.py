"""RealCaspianClient — production `CaspianClientProtocol` implementation against the real,
official `caspian-sdk` (Phase 6.6). The only file in this codebase that imports `caspian_sdk`
directly (besides its DI construction call in di_container.py) — everything above this file,
including `BridgeAgentHandler`, `ChannelAdapterRegistry`, `EmailAdapter`, `TelegramAdapter`,
and `CaspianGateway`, is unchanged and still depends only on `CaspianClientProtocol`. That is
the whole point of the seam this phase was asked to fill in, not redesign.

Read against the real SDK (`caspian_sdk.CommClient`, inspected directly from the installed
package before writing a line of this file — see the Phase 6.6 report), which looks nothing
like the placeholder shape `CaspianClientProtocol` was originally modeled on:

  - There is no `register_handler(handler)` / raw-payload callback on the real SDK. Inbound
    delivery is `client.on_message(handler)`, where `handler` receives a typed `Message`
    object (`id`, `conversation_id`, `channel`, `sender: dict`, `text`, ...) — one callback
    registration point for *every* connected channel, which maps naturally onto Bridge AI's
    own "exactly one handler" rule; `on_message` itself is this class's ONE call to it
    (enforced the same way `LocalCaspianClient` already does — raise on a second
    `register_handler`). This class's `_on_message` translates that `Message` into the
    `(channel: str, raw_payload: dict)` shape the existing `InboundHandler` contract expects,
    so `BridgeAgentHandler` never has to know `caspian_sdk.Message` exists.
  - There is no generic `send(channel, recipient, payload)` RPC either. Real outbound is
    either `client.initiate(connection_id, recipient, text)` (cold-start a new conversation)
    or `client.send_message(conversation_id, text)` (continue one that already exists). This
    class tracks a small `(channel, recipient) -> conversation_id` cache — learned from both
    outbound `initiate()` responses and inbound `Message.conversation_id` — so a repeat send
    to someone already in conversation continues that thread instead of cold-starting a new
    one every time, and implements `CaspianClientProtocol.send()` on top of the two real calls.
    Some channels cannot cold-initiate at all: confirmed live for Telegram (Phase 6.6.7), a
    `client.initiate()` call to a Telegram connection 422s with "Connection does not grant
    'initiate'" — a real platform constraint (a bot can only continue a chat the other side
    started), not a capability the gateway will ever grant. `_find_existing_conversation`
    checks `list_conversations()`/`list_messages()` for a conversation the recipient already
    has with us — e.g. from messaging the bot before this process ever started, which our own
    in-memory cache has no way to already know about — before ever assuming a cold `initiate()`
    is possible; `send()` uses whatever it finds instead of racing straight into that 422.
  - Channels aren't automatically live; each one is provisioned once via `connect_email()` /
    `connect_telegram(bot_token)`, which return a `connection_id`. `provision()` below does
    this at startup (called from app/main.py's lifespan, not at DI-construction time — see
    that module's docstring for why construction must stay I/O-free), reusing an existing
    active connection via `list_connections()` rather than minting a fresh one on every
    restart (connect_email() with no fixed username otherwise hands back a new random mailbox
    address each call — nothing in the documented SDK suggests repeat calls are idempotent).
  - Inbound delivery on a long-running server is either `client.listen()` — a blocking loop
    with no programmatic stop, unsuitable for a service that must shut down cleanly (Phase
    6.5's requirement, unchanged) — or `client.dispatch_pending(after_seq)`, which drains
    whatever's currently available and returns. `poll_once()` wraps the latter; a small,
    cleanly start/stoppable poller (app/infrastructure/caspian_poller.py, mirroring
    FollowupScheduler's own APScheduler pattern) calls it on an interval instead of using
    `listen()`.

Field-mapping, confirmed live (Phase 6.6.7 — a real /start + "hi" from a real Telegram user,
and a real inbound email): `caspian_sdk.Message.sender` uses `"address"` as one universal
per-channel identifier key on every channel checked so far — an email address for email
(`{"address": "tester@agents.trycaspianai.com", "name": None}`), a numeric Telegram user id
for telegram (`{"address": "8786421311", "name": "Anish Karthikeyan"}`) — not the
channel-specific `"email"`/`"handle"`/`"username"` keys originally guessed (Phase 6.6's report
flagged this as unverified at the time); those are kept only as a defensive fallback.

Conversation-reference discovery (Phase 6.6.6), verified live against the real gateway before
writing this: `initiate()` (cold-start) responds synchronously with only
`{"connection_id", "recipient", "status": "queued"}` — no conversation id at all, because the
send is asynchronous. `send_message()` (continuing a conversation we already know) responds
synchronously with the full message record, `conversation_id` included, since we already had
it to call it with. So a cold-start's conversation ref is not known until a later
`message.sent` event arrives on the event stream; `_await_conversation_id` waits briefly for
that event (matched by connection + recipient) rather than ever fabricating one. This is what
lets `send()` populate `CaspianSendResult.conversation_ref`, which is what
`DispatchMessageUseCase` (Part A of the cross-channel continuity fix) registers on the Case.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from caspian_sdk import CommClient, Message

from app.integrations.caspian_client import CaspianSendResult, InboundHandler

logger = logging.getLogger(__name__)

_KNOWN_CHANNELS = ("email", "telegram")
_SEND_CONFIRMATION_TIMEOUT_SECONDS = 10.0
_SEND_CONFIRMATION_POLL_INTERVAL_SECONDS = 1.0


class RealCaspianClient:
    """Adapts `caspian_sdk.CommClient` to `CaspianClientProtocol`. Constructing this does no
    I/O (matches `CommClient.__init__`, which only opens an `httpx.Client`, and `LocalCaspianClient`'s
    own zero-I/O constructor) — `provision()` is the one method that actually talks to Caspian's
    API, and is called once, explicitly, from app startup.
    """

    def __init__(self, comm_client: CommClient) -> None:
        self._client = comm_client
        self._handler: InboundHandler | None = None
        self._connections: dict[str, str] = {}
        """channel -> Caspian connection_id, populated by provision()."""
        self._conversations: dict[tuple[str, str], str] = {}
        """(channel, recipient_address) -> Caspian conversation_id — the continuity cache
        described in the module docstring."""
        self._last_seq: int | None = None
        """Polling cursor; None until established (see register_handler / poll_once) — never
        left at the implicit "beginning of history" default a bare 0 would mean."""

    # --- provisioning (Part "Channel Requirement" — actually connect the channels) --------

    def provision(
        self, *, email_username: str | None = None, telegram_bot_token: str | None = None
    ) -> dict[str, str]:
        """Connects every channel — reusing whatever Caspian already owns for this project
        (e.g. a connection made once via `caspian-cli`, independent of this process) before
        ever considering creating a new one. `list_connections()` is checked FIRST for every
        channel, `telegram_bot_token` unconditionally — a channel Caspian already has an
        active connection for needs no local credential to be rediscovered and reused; a bot
        token is only needed as a fallback to *create* a telegram connection that doesn't
        exist yet. Safe to call once per process start. Returns the channel -> connection_id
        map for logging; a channel that fails to connect is logged and skipped, not fatal to
        the others or to app startup — the same "degrade, don't fail" posture the rest of
        this codebase uses for a missing policy-pack entry or an unresolved role.
        """
        self._ensure_connection(
            "email", lambda: self._client.connect_email(username=email_username)
        )
        self._ensure_connection("telegram", lambda: self._connect_telegram(telegram_bot_token))
        return dict(self._connections)

    def _connect_telegram(self, bot_token: str | None) -> dict[str, Any]:
        if not bot_token:
            raise RuntimeError(
                "No existing Caspian telegram connection found and no TELEGRAM_BOT_TOKEN "
                "configured to create one — either connect telegram via caspian-cli first, "
                "or set TELEGRAM_BOT_TOKEN."
            )
        connection: dict[str, Any] = self._client.connect_telegram(bot_token)
        return connection

    def _ensure_connection(self, channel: str, connect: Any) -> None:
        try:
            existing = self._client.list_connections(channel=channel)
        except Exception:
            logger.exception("Failed to list existing Caspian '%s' connections", channel)
            existing = []

        # Verified against the real gateway (Phase 6.6 live check): list_connections'
        # channel= query param is NOT applied server-side — it returns every connection on
        # every call regardless of the filter requested. Trusting it silently picked the
        # email connection for a telegram lookup too. Filtering client-side is the fix; it's
        # correct even if the server-side filter is later fixed upstream (a no-op then).
        existing = [c for c in existing if c.get("channel") == channel]

        active = next((c for c in existing if c.get("status") == "active"), None)
        if active is not None:
            self._connections[channel] = active["id"]
            logger.info("Reusing active Caspian %s connection %s", channel, active["id"])
            return
        if existing:
            # A non-active connection (still provisioning, or failed) — reuse its id rather
            # than mint a duplicate; a failed one will simply keep failing sends, which
            # surfaces via CaspianSendResult.success=False same as any other send failure.
            self._connections[channel] = existing[0]["id"]
            logger.warning(
                "Caspian %s connection %s exists but is not active (status=%s)",
                channel,
                existing[0]["id"],
                existing[0].get("status"),
            )
            return
        try:
            connection = connect()
        except Exception:
            logger.exception("Failed to connect Caspian '%s' channel", channel)
            return
        self._connections[channel] = connection["id"]
        logger.info(
            "Connected Caspian %s: %s (%s)",
            channel,
            connection["id"],
            connection.get("address") or connection.get("status"),
        )

    # --- CaspianClientProtocol ---------------------------------------------------------------

    def register_handler(self, handler: InboundHandler) -> None:
        if self._handler is not None:
            raise RuntimeError(
                "A handler is already registered — only one Caspian handler is allowed."
            )
        self._handler = handler
        self._client.on_message(self._on_message)
        # Establish the polling cursor at "now", not at the beginning of this Caspian
        # project's entire event history. `dispatch_pending(after_seq=0)` (unlike
        # `client.listen(from_seq=None)`, which defaults to this same "start from now"
        # behavior internally) has no such default of its own — without this, every fresh
        # RealCaspianClient (i.e. every process restart in production) would replay every
        # event ever delivered to this project on its very first poll, re-running the full
        # reasoning pipeline and re-dispatching for messages already handled, or never meant
        # to be. Confirmed live during Phase 6.6.5 verification: a fresh instance's first
        # poll_once() reprocessed several days-old test emails from earlier manual/live test
        # runs. Set here, not in poll_once(), so it's established before any traffic that
        # arrives after startup — the same point app/main.py's lifespan calls this from.
        self._last_seq = self._current_latest_seq()

    def send(self, channel: str, recipient: str, payload: dict[str, Any]) -> CaspianSendResult:
        text = payload.get("body") or payload.get("text")
        if not text:
            return CaspianSendResult(success=False, error="No message text in outbound payload")

        key = (channel, recipient)
        try:
            conversation_id = self._conversations.get(key)
            connection_id = self._connections.get(channel)
            if conversation_id is None and connection_id is not None:
                # Some channels cannot cold-start a conversation at all — confirmed live for
                # Telegram (Phase 6.6.7): initiate() 422s with "Connection does not grant
                # 'initiate'". This is a real platform constraint (a bot can only continue a
                # chat the other side started), not something retrying fixes. A recipient who
                # already has a real conversation with this connection — e.g. they messaged
                # the bot before this process ever started, so our own in-memory
                # `_conversations` cache has no way to already know about it — is
                # discoverable via list_conversations()/list_messages(); check before ever
                # assuming a cold initiate() is the only option.
                conversation_id = self._find_existing_conversation(connection_id, recipient)

            if conversation_id is not None:
                result = self._client.send_message(conversation_id, text=text)
                # send_message() always echoes conversation_id back (verified live) — trust
                # it over our own cache in case the gateway ever migrates/merges threads.
                conversation_id = result.get("conversation_id") or conversation_id
            else:
                if connection_id is None:
                    return CaspianSendResult(
                        success=False, error=f"No Caspian connection provisioned for '{channel}'"
                    )
                seq_before_send = self._current_latest_seq()
                result = self._client.initiate(connection_id, recipient=recipient, text=text)
                # initiate()'s synchronous response never carries a conversation id (verified
                # live — see module docstring); wait briefly for the async confirmation
                # rather than returning a send with no discoverable continuity.
                conversation_id = result.get("conversation_id") or self._await_conversation_id(
                    connection_id=connection_id, recipient=recipient, after_seq=seq_before_send
                )
            if conversation_id:
                self._conversations[key] = conversation_id
        except Exception as exc:
            # Never let a send failure raise out of DispatchMessageUseCase — a FAILED
            # CaspianSendResult is how that use case already expects a send to fail, and
            # the exception's own message (from caspian_sdk's CommError etc.) never
            # includes the API key, only gateway-reported status/detail.
            logger.exception("Caspian send failed on channel '%s'", channel)
            return CaspianSendResult(success=False, error=str(exc))

        message_id = result.get("id") or result.get("message_id")
        # A successful, real Caspian send (the API accepted it) still counts as SUCCESS even
        # if conversation_id ends up None (e.g. the confirmation timed out) — Part E is
        # explicit that dispatch success must track the send, not continuity discovery.
        # DispatchMessageUseCase logs plainly when conversation_ref comes back empty rather
        # than silently pretending continuity was registered.
        return CaspianSendResult(
            success=True,
            external_message_ref=str(message_id) if message_id else None,
            conversation_ref=conversation_id,
        )

    def _find_existing_conversation(self, connection_id: str, recipient: str) -> str | None:
        """Scans this connection's existing conversations for one already involving
        `recipient`, so send() can reuse it via send_message() instead of assuming a cold
        initiate() is possible (it isn't, for every channel — see send()'s docstring).
        conversation objects carry no participant field of their own (verified live); the
        match has to be against their messages' sender/recipients. Bounded by how many
        conversations a channel actually has — fine at hackathon-MVP scale, not something
        that scales to a channel with thousands of threads without a real search API.
        """
        try:
            conversations = self._client.list_conversations(connection_id=connection_id)
        except Exception:
            logger.exception("Failed to list conversations while searching for '%s'", recipient)
            return None
        for conversation in conversations:
            try:
                messages = self._client.list_messages(conversation["id"])
            except Exception:
                logger.exception("Failed to list messages for conversation %s", conversation["id"])
                continue
            for message in messages:
                if _address_matches(message.get("sender") or {}, recipient):
                    return str(conversation["id"])
                if any(_address_matches(r, recipient) for r in message.get("recipients") or []):
                    return str(conversation["id"])
        return None

    def _await_conversation_id(
        self, *, connection_id: str, recipient: str, after_seq: int
    ) -> str | None:
        """Polls for the `message.sent` event confirming a just-submitted `initiate()` call,
        matched by connection and recipient address, and returns its `conversation_id`.
        Bounded — returns None (never raises) on timeout, since the send itself already
        succeeded; DispatchMessageUseCase is what decides how to log a missing ref."""
        deadline = time.monotonic() + _SEND_CONFIRMATION_TIMEOUT_SECONDS
        seq = after_seq
        while time.monotonic() < deadline:
            try:
                events = self._client.events(after_seq=seq, limit=100, type="message.sent")
            except Exception:
                logger.exception("Failed to poll for Caspian send confirmation")
                return None
            for event in events:
                seq = max(seq, event.get("seq", seq))
                message = (event.get("data") or {}).get("message") or {}
                if message.get("connection_id") != connection_id:
                    continue
                if any(_address_matches(r, recipient) for r in message.get("recipients") or []):
                    return message.get("conversation_id")
            time.sleep(_SEND_CONFIRMATION_POLL_INTERVAL_SECONDS)
        logger.warning(
            "Timed out after %.0fs waiting for Caspian to confirm the conversation for a "
            "send to '%s' — the send itself already succeeded; reply continuity for this "
            "recipient will not be registered for this particular dispatch.",
            _SEND_CONFIRMATION_TIMEOUT_SECONDS,
            recipient,
        )
        return None

    # --- inbound polling (app/infrastructure/caspian_poller.py calls this on an interval) --

    def poll_once(self) -> int:
        """Drains every currently pending event once (`caspian_sdk`'s own
        `dispatch_pending`) and advances this client's cursor. Returns the new cursor.
        Falls back to establishing the cursor here too (same as register_handler) in case
        this is ever called before a handler was registered — defends the same "never
        replay history" guarantee regardless of call order.
        """
        if self._last_seq is None:
            self._last_seq = self._current_latest_seq()
        self._last_seq = self._client.dispatch_pending(after_seq=self._last_seq)
        return self._last_seq

    def _current_latest_seq(self) -> int:
        """The newest seq available right now — using only the public `events()` API, the
        same paging `caspian_sdk`'s own `listen(from_seq=None)` does internally to skip
        history on startup (see poll_once/register_handler for why `dispatch_pending` needs
        this established explicitly)."""
        seq = 0
        while True:
            batch = self._client.events(after_seq=seq, limit=500)
            if not batch:
                return seq
            seq = batch[-1]["seq"]

    def close(self) -> None:
        self._client.close()

    # --- translation ---------------------------------------------------------------------

    def _on_message(self, message: Message) -> None:
        recipient = _sender_address(message)
        if recipient:
            self._conversations[(message.channel, recipient)] = message.conversation_id

        if self._handler is None:
            logger.warning("Caspian message %s arrived with no handler registered", message.id)
            return
        self._handler(message.channel, _to_raw_payload(message))


def _address_matches(recipient_record: dict[str, Any], recipient: str) -> bool:
    return (recipient_record.get("address") or "").strip().lower() == recipient.strip().lower()


def _sender_address(message: Message) -> str | None:
    """`sender["address"]` is Caspian's one universal per-channel identifier — confirmed live
    for both channels (Phase 6.6.7 investigation): an email address for the email channel
    (`{"address": "tester@agents.trycaspianai.com", "name": None}`), a numeric Telegram user
    id for the telegram channel (`{"address": "8786421311", "name": "Anish Karthikeyan"}`).
    The original guesses ("email"/"handle"/"username") were flagged as unverified in the
    Phase 6.6 report; kept here only as a fallback in case some other channel or a future SDK
    version ever uses one of those key names instead."""
    sender = message.sender or {}
    return (
        sender.get("address")
        or sender.get("email")
        or sender.get("handle")
        or sender.get("username")
    )


def _to_raw_payload(message: Message) -> dict[str, Any]:
    """Caspian's normalized `Message` -> the envelope shape EmailAdapter and TelegramAdapter
    both parse (see telegram_adapter.py's docstring for why they share one shape now)."""
    sender = message.sender or {}
    address = _sender_address(message)
    name = sender.get("name") or address or "Unknown"

    return {
        "from": {
            "name": name,
            "email": address if message.channel == "email" else sender.get("email"),
            "telegram_handle": (
                address
                if message.channel == "telegram"
                else sender.get("handle") or sender.get("username")
            ),
            "role": sender.get("role"),
        },
        "cc": [],  # caspian_sdk.Message carries no separate cc list at this SDK version
        "subject": message.subject,
        "body": message.text or "",
        "thread_ref": message.conversation_id,
        "message_ref": message.id,
    }
