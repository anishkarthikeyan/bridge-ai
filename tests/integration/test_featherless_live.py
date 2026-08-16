"""Live Featherless integration test (Phase 6.5 Parts 6/16) — the one place in this suite
that calls the real, configured Featherless endpoint with the real, configured DeepSeek-V3.2
model (app/integrations/llm/featherless_client.py). Skips cleanly, not as a failure, when no
API key is configured (Part 6: "If the API key is unavailable in the test environment, skip
the live integration test clearly rather than failing unrelated tests") — every other test in
this suite runs against FakeLLMPort or a scripted fake client and never depends on this file.

Deliberately minimal: exactly one live call per permitted LLM task (four total) — "keep live
inference tests minimal because inference credits are limited." The API key itself is never
printed or asserted on directly, only that it's present (Part 14).
"""

from __future__ import annotations

import pytest

from app.application.ports.llm_port import (
    EntitiesResult,
    IntentResult,
    MessageGenerationContext,
    TopicClassification,
)
from app.infrastructure.config import get_settings
from app.integrations.llm.featherless_client import FeatherlessClient

pytestmark = pytest.mark.skipif(
    not get_settings().featherless_api_key,
    reason="FEATHERLESS_API_KEY not configured — skipping live Featherless integration test",
)

_MESSAGE = (
    "We're changing refunds to settle same-day instead of the current 3-day hold. Wanted "
    "Finance looped in before this ships next week."
)


@pytest.fixture(scope="module")
def client() -> FeatherlessClient:
    return FeatherlessClient()


def test_classify_topic_returns_a_valid_topic_classification(client: FeatherlessClient) -> None:
    result = client.classify_topic(_MESSAGE)
    assert isinstance(result, TopicClassification)
    assert isinstance(result.topic, str) and result.topic
    assert 0.0 <= result.confidence <= 1.0


def test_extract_intent_returns_a_valid_intent_result(client: FeatherlessClient) -> None:
    result = client.extract_intent(_MESSAGE)
    assert isinstance(result, IntentResult)
    assert isinstance(result.intent, str) and result.intent
    assert 0.0 <= result.confidence <= 1.0


def test_extract_entities_returns_a_valid_entities_result(client: FeatherlessClient) -> None:
    result = client.extract_entities(_MESSAGE)
    assert isinstance(result, EntitiesResult)
    assert isinstance(result.people, tuple)
    assert isinstance(result.mentioned_roles, tuple)
    assert isinstance(result.dates, tuple)


def test_generate_message_returns_nonempty_text(client: FeatherlessClient) -> None:
    text = client.generate_message(
        MessageGenerationContext(
            topic="payment_system",
            missing_roles=("Security", "Support"),
            channel="email",
            recipient_name="John Ortiz",
            case_summary="Topic: payment_system. Missing roles: Security, Support. Priority: high.",
        )
    )
    assert isinstance(text, str) and text.strip()
