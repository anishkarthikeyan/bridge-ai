"""ChannelPort — abstract interface every channel adapter implements: send() and
parse_inbound(). DispatchMessageUseCase's `ChannelPort.send()` call is the *only* place in
the codebase that sends an outbound message (architecture doc §9; Phase 5 rule: "only one
Caspian handler," mirrored on the outbound side as "only one dispatch call site").

`send()` takes the OutboundAction as-is — the adapter builds its own wire format internally
(a private detail of each adapter, not part of this interface, since email and Telegram
payloads share no common shape) and delegates the actual transmission to a CaspianGateway
each adapter is constructed with. That keeps adapters "dumb": formatting and delegating are
mechanical, not decisions — nothing here chooses who, when, or which channel; those were
already decided by the brain before an OutboundAction ever exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.application.dto.inbound_message import InboundMessage
from app.domain.entities.outbound_action import OutboundAction


@dataclass(frozen=True)
class SendResult:
    success: bool
    external_message_ref: str | None = None
    error: str | None = None
    conversation_ref: str | None = None
    """The gateway's own conversation/thread identifier for this send, when known (Phase
    6.6.6) — what DispatchMessageUseCase registers on the Case so a later reply on this exact
    (channel, conversation_ref) resolves back to it via CaseRepositoryPort.find_by_conversation_ref,
    instead of opening a new Case. None when the gateway couldn't determine it (e.g. an
    asynchronous cold-start send whose conversation isn't confirmed yet) — never fabricated."""


class ChannelPort(ABC):
    @abstractmethod
    def send(self, action: OutboundAction) -> SendResult: ...

    @abstractmethod
    def parse_inbound(self, raw: dict) -> InboundMessage: ...
