"""Unit tests for FeatherlessClient (Phase 6.5 Parts 1/3/4/5) — no real network calls here;
the underlying `openai` client is replaced with a small scripted fake (`_FakeOpenAI`) so every
path — success, malformed JSON, transient retry, non-retryable error, the json-mode
capability fallback — is exercised deterministically and instantly. The live Featherless
integration itself is covered separately by tests/integration/test_featherless_live.py, which
skips cleanly without an API key (Part 6).
"""

from __future__ import annotations

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, BadRequestError

from app.application.ports.llm_port import (
    LLMRequestError,
    LLMResponseError,
    LLMTransientError,
    MessageGenerationContext,
)
from app.infrastructure.config import Settings
from app.integrations.llm.featherless_client import FeatherlessClient


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "featherless_api_key": "test-key",
        "featherless_base_url": "https://api.featherless.ai/v1",
        "featherless_model": "deepseek-ai/DeepSeek-V3.2",
        "featherless_http_referer": "",
        "featherless_x_title": "Bridge AI",
        "llm_temperature": 0.2,
        "llm_max_tokens": 256,
        "llm_timeout_seconds": 5,
        "llm_max_retries": 2,
        "llm_retry_backoff_seconds": 0.0,  # no real sleeping in tests
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _error_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.featherless.ai/v1/chat/completions")
    return httpx.Response(status_code, request=request)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": content})()})()]


class _FakeCompletions:
    """Pops one scripted step per call — a string becomes a successful response, an
    Exception instance is raised. Records every call's kwargs for assertions."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError("FeatherlessClient made more requests than the test scripted")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return _FakeResponse(step)


class _FakeOpenAI:
    def __init__(self, script: list) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(script)})()


def _client(script: list, **settings_overrides: object) -> tuple[FeatherlessClient, _FakeOpenAI]:
    fake = _FakeOpenAI(script)
    return FeatherlessClient(_settings(**settings_overrides), client=fake), fake  # type: ignore[arg-type]


# --- construction / configuration (Part 1 / Part 5) ---------------------------------------


def test_model_comes_from_settings_not_hardcoded() -> None:
    client, fake = _client(['{"intent": "x", "confidence": 0.5}'])
    client.extract_intent("hi")
    assert fake.chat.completions.calls[0]["model"] == "deepseek-ai/DeepSeek-V3.2"


def test_attribution_headers_are_configurable_and_referer_omitted_when_blank() -> None:
    real_client = FeatherlessClient(
        _settings(featherless_http_referer="", featherless_x_title="Bridge AI")
    )
    assert "X-Title" in real_client._client.default_headers
    assert real_client._client.default_headers["X-Title"] == "Bridge AI"
    assert "HTTP-Referer" not in real_client._client.default_headers


def test_http_referer_is_sent_when_configured() -> None:
    real_client = FeatherlessClient(_settings(featherless_http_referer="https://bridge.ai"))
    assert real_client._client.default_headers["HTTP-Referer"] == "https://bridge.ai"


def test_timeout_and_own_retry_ownership_come_from_settings() -> None:
    real_client = FeatherlessClient(_settings(llm_timeout_seconds=42))
    assert real_client._client.timeout == 42.0
    assert real_client._client.max_retries == 0  # FeatherlessClient owns 100% of retrying


# --- successful structured output (Part 3) --------------------------------------------------


def test_extract_intent_success() -> None:
    client, _ = _client(['{"intent": "request_review", "confidence": 0.87}'])
    result = client.extract_intent("Please review the payment flow change.")
    assert result.intent == "request_review"
    assert result.confidence == pytest.approx(0.87)


def test_confidence_on_a_0_100_scale_is_normalized_to_0_1() -> None:
    client, _ = _client(['{"topic": "payment_system", "confidence": 87}'])
    result = client.classify_topic("...")
    assert result.confidence == pytest.approx(0.87)


def test_extract_entities_success() -> None:
    client, _ = _client(
        ['{"people": ["Dana Kapoor"], "mentioned_roles": ["Security"], "dates": []}']
    )
    result = client.extract_entities("...")
    assert result.people == ("Dana Kapoor",)
    assert result.mentioned_roles == ("Security",)
    assert result.dates == ()


def test_generate_message_returns_plain_text_without_json_parsing() -> None:
    client, fake = _client(["Hi John, could you take a look at this?"])
    text = client.generate_message(
        MessageGenerationContext(
            topic="payment_system",
            missing_roles=("Security",),
            channel="email",
            recipient_name="John Ortiz",
            case_summary="Topic: payment_system.",
        )
    )
    assert text == "Hi John, could you take a look at this?"
    assert "response_format" not in fake.chat.completions.calls[0]


# --- malformed output is rejected, never silently accepted, never retried (Part 3) ----------


def test_non_json_response_raises_llm_response_error_without_retrying() -> None:
    client, fake = _client(["not json at all"])
    with pytest.raises(LLMResponseError):
        client.extract_intent("hi")
    assert len(fake.chat.completions.calls) == 1  # malformed output is never retried


def test_json_missing_required_field_raises_llm_response_error() -> None:
    client, _ = _client(['{"confidence": 0.5}'])
    with pytest.raises(LLMResponseError):
        client.extract_intent("hi")


def test_wrong_type_for_array_field_raises_llm_response_error() -> None:
    client, _ = _client(['{"people": "Dana Kapoor", "mentioned_roles": [], "dates": []}'])
    with pytest.raises(LLMResponseError):
        client.extract_entities("hi")


def test_json_wrapped_in_markdown_fence_is_still_parsed() -> None:
    client, _ = _client(['```json\n{"intent": "request_review", "confidence": 0.9}\n```'])
    result = client.extract_intent("hi")
    assert result.intent == "request_review"


def test_empty_generated_message_raises_llm_response_error() -> None:
    client, _ = _client([""])
    with pytest.raises(LLMResponseError):
        client.generate_message(
            MessageGenerationContext(
                topic=None, missing_roles=(), channel="email", recipient_name="x", case_summary="x"
            )
        )


# --- bounded retry on transient failures only (Part 4) --------------------------------------


def test_retries_on_429_then_succeeds() -> None:
    client, fake = _client(
        [
            APIStatusError("rate limited", response=_error_response(429), body=None),
            '{"intent": "request_review", "confidence": 0.9}',
        ],
        llm_max_retries=2,
    )
    result = client.extract_intent("hi")
    assert result.intent == "request_review"
    assert len(fake.chat.completions.calls) == 2


def test_retries_on_connection_error_then_succeeds() -> None:
    request = httpx.Request("POST", "https://api.featherless.ai/v1/chat/completions")
    client, fake = _client(
        [
            APIConnectionError(request=request),
            '{"intent": "request_review", "confidence": 0.9}',
        ],
        llm_max_retries=2,
    )
    client.extract_intent("hi")
    assert len(fake.chat.completions.calls) == 2


def test_exhausting_retries_raises_llm_transient_error() -> None:
    client, fake = _client(
        [
            APIStatusError("rate limited", response=_error_response(429), body=None),
            APIStatusError("rate limited", response=_error_response(429), body=None),
        ],
        llm_max_retries=1,
    )
    with pytest.raises(LLMTransientError):
        client.extract_intent("hi")
    assert len(fake.chat.completions.calls) == 2  # 1 initial attempt + 1 retry, then stop


def test_non_retryable_status_error_raises_immediately() -> None:
    client, fake = _client(
        [APIStatusError("unauthorized", response=_error_response(401), body=None)],
        llm_max_retries=3,
    )
    with pytest.raises(LLMRequestError):
        client.extract_intent("hi")
    assert len(fake.chat.completions.calls) == 1  # never retried — not a transient status


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_every_documented_retryable_status_is_retried(status_code: int) -> None:
    client, fake = _client(
        [
            APIStatusError("transient", response=_error_response(status_code), body=None),
            '{"intent": "x", "confidence": 0.5}',
        ],
        llm_max_retries=1,
    )
    client.extract_intent("hi")
    assert len(fake.chat.completions.calls) == 2


# --- json-mode capability fallback (Part 3) --------------------------------------------------


def test_response_format_unsupported_falls_back_within_the_same_call() -> None:
    client, fake = _client(
        [
            BadRequestError(
                "response_format not supported", response=_error_response(400), body=None
            ),
            '{"intent": "request_review", "confidence": 0.9}',
        ]
    )
    result = client.extract_intent("hi")
    assert result.intent == "request_review"
    assert len(fake.chat.completions.calls) == 2
    assert "response_format" in fake.chat.completions.calls[0]
    assert "response_format" not in fake.chat.completions.calls[1]


def test_json_mode_fallback_is_sticky_across_calls() -> None:
    client, fake = _client(
        [
            BadRequestError("nope", response=_error_response(400), body=None),
            '{"intent": "a", "confidence": 0.5}',
            '{"topic": "b", "confidence": 0.5}',
        ]
    )
    client.extract_intent("hi")
    client.classify_topic("hi")
    # Second LLM call never re-attempts response_format=json_object at all.
    assert "response_format" not in fake.chat.completions.calls[2]
