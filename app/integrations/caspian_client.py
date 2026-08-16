"""CaspianClient — our side of the contract with the Caspian SDK.

`CaspianClientProtocol` is the minimal surface CaspianGateway and BridgeAgentHandler actually
need — register one handler for inbound events, send one outbound message. The real
`caspian-sdk` package (Phase 6.6) is fulfilled by `app/integrations/real_caspian_client.py`'s
`RealCaspianClient`, a thin adapter implementing this same Protocol; nothing that depends on
the Protocol needs to know which implementation is wired in.

`LocalCaspianClient` is a stand-in that fulfills the Protocol without any live external
service — it records every send in memory and lets a caller simulate an inbound event
(`simulate_inbound`), which is what makes this build's end-to-end flow demonstrable and
testable without real Caspian credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4


@dataclass(frozen=True)
class CaspianSendResult:
    success: bool
    external_message_ref: str | None = None
    error: str | None = None
    conversation_ref: str | None = None
    """The Caspian conversation/thread id this send used, when known — see SendResult's own
    field of the same name (app/application/ports/channel_port.py) for the full rationale;
    this is that same value one layer closer to the real API."""


InboundHandler = Callable[[str, dict[str, Any]], None]


class CaspianClientProtocol(Protocol):
    def register_handler(self, handler: InboundHandler) -> None:
        """Registers THE handler for every inbound event, on every channel. Calling this
        more than once is a configuration error a real client should reject — Phase 5's
        rule is "only one Caspian handler," enforced at the composition root by calling
        this exactly once (see app/infrastructure/di_container.py)."""
        ...

    def send(self, channel: str, recipient: str, payload: dict[str, Any]) -> CaspianSendResult: ...


@dataclass
class _RecordedSend:
    channel: str
    recipient: str
    payload: dict[str, Any]


class LocalCaspianClient:
    """In-memory stand-in for the real Caspian SDK client. Not a mock in the unit-test
    sense — it's a real, working implementation of CaspianClientProtocol, just one that
    "delivers" by recording rather than by talking to an external service."""

    def __init__(self) -> None:
        self.sent: list[_RecordedSend] = []
        self._handler: InboundHandler | None = None
        self._conversations: dict[tuple[str, str], str] = {}
        """(channel, recipient) -> a synthesized conversation ref, stable per pair — mirrors
        RealCaspianClient's own continuity cache closely enough for tests to exercise
        DispatchMessageUseCase's conversation-registration logic (Phase 6.6.6) without the
        real SDK: a repeat send to the same recipient reuses the same ref instead of a fresh
        one each time, exactly like a real Caspian conversation would."""

    def register_handler(self, handler: InboundHandler) -> None:
        if self._handler is not None:
            raise RuntimeError(
                "A handler is already registered — only one Caspian handler is allowed."
            )
        self._handler = handler

    def send(self, channel: str, recipient: str, payload: dict[str, Any]) -> CaspianSendResult:
        self.sent.append(_RecordedSend(channel=channel, recipient=recipient, payload=payload))
        key = (channel, recipient)
        conversation_ref = self._conversations.setdefault(key, f"local-conv-{uuid4()}")
        return CaspianSendResult(
            success=True, external_message_ref=str(uuid4()), conversation_ref=conversation_ref
        )

    def simulate_inbound(self, channel: str, raw_payload: dict[str, Any]) -> None:
        """Test/demo helper: delivers a raw inbound event to whatever handler is
        registered, exactly as a real Caspian webhook would."""
        if self._handler is None:
            raise RuntimeError("No handler registered — nothing to deliver the event to.")
        self._handler(channel, raw_payload)
