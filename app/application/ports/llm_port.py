"""LLMPort — abstract interface for the LLM client, scoped to exactly the four permitted
tasks: intent extraction, entity extraction, topic classification, and message generation.
Nothing else — see architecture doc §3 (LLM boundary): the model classifies and generates,
it never decides.

Brain nodes depend on this interface, never on a concrete client. The real implementation
(app/integrations/llm/featherless_client.py, Phase 6.5) talks to Featherless's
OpenAI-compatible API; FakeLLMPort (tests/unit/brain/fakes.py) is the deterministic stand-in
every existing test still uses. Nodes are independently testable by constructing them with
either.

The exception hierarchy below is the "controlled domain/application error" every LLMPort
implementation is expected to raise instead of ever silently accepting malformed output (see
FeatherlessClient's docstring, Phase 6.5 Part 3/4) — a shared contract, not something specific
to one client, so a brain node or use case can catch `LLMPortError` regardless of which
implementation is wired in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMPortError(Exception):
    """Base class for every exception an LLMPort implementation raises."""


class LLMTransientError(LLMPortError):
    """A transient failure (rate limit, server error, timeout, connection) that persisted
    after the implementation's own bounded retries were exhausted."""


class LLMRequestError(LLMPortError):
    """A non-retryable request failure (e.g. HTTP 400/401/403/404) — retrying would not have
    helped, so the implementation did not retry it."""


class LLMResponseError(LLMPortError):
    """The model responded, but its content could not be parsed or validated into the
    expected DTO. Never retried — malformed model output is a controlled failure, not a
    transient one (Part 3: "Do NOT silently accept malformed AI output")."""


@dataclass(frozen=True)
class IntentResult:
    intent: str
    confidence: float


@dataclass(frozen=True)
class EntitiesResult:
    people: tuple[str, ...] = ()
    mentioned_roles: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopicClassification:
    topic: str
    confidence: float


@dataclass(frozen=True)
class MessageGenerationContext:
    topic: str | None
    missing_roles: tuple[str, ...]
    channel: str
    recipient_name: str
    case_summary: str


class LLMPort(ABC):
    @abstractmethod
    def extract_intent(self, text: str) -> IntentResult: ...

    @abstractmethod
    def extract_entities(self, text: str) -> EntitiesResult: ...

    @abstractmethod
    def classify_topic(self, text: str) -> TopicClassification: ...

    @abstractmethod
    def generate_message(self, context: MessageGenerationContext) -> str: ...
