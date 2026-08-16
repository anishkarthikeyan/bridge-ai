"""FeatherlessClient — implements LLMPort via the OpenAI-compatible Featherless API.

Uses the official `openai` Python SDK (not LangChain — Part 1 of the Phase 6.5 spec is
explicit about that), pointed at Featherless's base URL. Every request goes through exactly
two paths, both scoped to the four permitted LLM tasks (architecture doc §3 — the model
classifies and generates, it never decides):

  - `_complete_json()` — extract_intent, extract_entities, classify_topic. Asks the model for
    strict JSON (via `response_format={"type": "json_object"}` when the model/endpoint
    supports it, always reinforced by an explicit "respond with ONLY JSON" instruction in the
    prompt as a fallback for when it doesn't — see `_call_once`), then parses and validates
    the result against the exact shape the existing LLMPort DTOs (IntentResult, EntitiesResult,
    TopicClassification) already declare. Malformed output is never silently accepted and
    never retried — it's rejected via `LLMResponseError` (Part 3).
  - `generate_message()` — plain text, no JSON involved.

Retries (Part 4) are bounded and apply ONLY to transient transport/server failures — HTTP
429/500/502/503/504, connection errors, timeouts — via exponential backoff, entirely
config-driven (`Settings.llm_max_retries`, `Settings.llm_retry_backoff_seconds`). The
underlying `openai.OpenAI` client is constructed with its own `max_retries=0` so retry
behavior is decided in exactly one place (this class), not doubled up with the SDK's built-in
retry loop. A non-retryable HTTP error (e.g. 400/401/403/404) is never retried and surfaces
immediately as `LLMRequestError`.

The API key is read once from Settings at construction and handed to the SDK client, which
puts it on the Authorization header — it is never interpolated into a log line, an exception
message, or a prompt anywhere in this file (Part 4 / Part 14).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    OpenAI,
)

from app.application.ports.llm_port import (
    EntitiesResult,
    IntentResult,
    LLMPort,
    LLMRequestError,
    LLMResponseError,
    LLMTransientError,
    MessageGenerationContext,
    TopicClassification,
)
from app.infrastructure.config import Settings, get_settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Guidance only, not a hard constraint — classify_topic may still return a topic outside this
# set (e.g. the customer_escalation demo scenario is deliberately outside the software pack);
# LoadPolicyNode already degrades gracefully for a topic with no policy entry.
_KNOWN_TOPICS = ("authentication_change", "database_migration", "payment_system")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class FeatherlessClient(LLMPort):
    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None) -> None:
        self._settings = settings or get_settings()

        default_headers: dict[str, str] = {}
        if self._settings.featherless_http_referer:
            default_headers["HTTP-Referer"] = self._settings.featherless_http_referer
        if self._settings.featherless_x_title:
            default_headers["X-Title"] = self._settings.featherless_x_title

        self._client = client or OpenAI(
            api_key=self._settings.featherless_api_key,
            base_url=self._settings.featherless_base_url,
            timeout=float(self._settings.llm_timeout_seconds),
            max_retries=0,  # this class owns 100% of retry behavior, see module docstring
            default_headers=default_headers or None,
        )
        self._model = self._settings.featherless_model
        # Sticky capability flag: flips False the first time the endpoint rejects
        # response_format=json_object, so every later call skips straight to the prompt-only
        # fallback instead of re-discovering the same 400 every time (Part 3's fallback path).
        self._supports_json_mode = True

    # --- LLMPort ---------------------------------------------------------------------------

    def extract_intent(self, text: str) -> IntentResult:
        data = self._complete_json(
            system=(
                "You are the intent-classification component of Bridge AI, a workplace "
                "communication agent. Classify the sender's intent in ONE short snake_case "
                "label (e.g. request_review, status_update, question, approval, confirmation, "
                "escalation_request, other). Respond with ONLY a JSON object of the exact "
                'shape {"intent": string, "confidence": number between 0 and 1}. No prose, '
                "no markdown fences, no extra keys."
            ),
            user=f"Message:\n{text}",
        )
        intent = data.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            raise LLMResponseError(f"extract_intent: missing/invalid 'intent' field in {data!r}")
        return IntentResult(
            intent=intent.strip(), confidence=_coerce_confidence(data.get("confidence"))
        )

    def extract_entities(self, text: str) -> EntitiesResult:
        data = self._complete_json(
            system=(
                "You are the entity-extraction component of Bridge AI. Extract every person "
                "named, every organizational role mentioned (e.g. Security, Finance, QA, DBA, "
                "DevOps, Support, Product), and every date or deadline mentioned in the "
                'message. Respond with ONLY a JSON object of the exact shape {"people": '
                '[string, ...], "mentioned_roles": [string, ...], "dates": [string, ...]}. '
                "Use empty arrays for anything not present. No prose, no markdown fences, no "
                "extra keys."
            ),
            user=f"Message:\n{text}",
        )
        return EntitiesResult(
            people=_coerce_str_tuple(data.get("people", []), field="people"),
            mentioned_roles=_coerce_str_tuple(
                data.get("mentioned_roles", []), field="mentioned_roles"
            ),
            dates=_coerce_str_tuple(data.get("dates", []), field="dates"),
        )

    def classify_topic(self, text: str) -> TopicClassification:
        data = self._complete_json(
            system=(
                "You are the topic-classification component of Bridge AI. Classify the "
                "message into a short snake_case topic label. Known topics in the current "
                f"policy pack include: {', '.join(_KNOWN_TOPICS)} — use one of these if it "
                "genuinely fits, otherwise choose the best short snake_case label for what "
                "the message is actually about. Respond with ONLY a JSON object of the exact "
                'shape {"topic": string, "confidence": number between 0 and 1}. No prose, no '
                "markdown fences, no extra keys."
            ),
            user=f"Message:\n{text}",
        )
        topic = data.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise LLMResponseError(f"classify_topic: missing/invalid 'topic' field in {data!r}")
        return TopicClassification(
            topic=topic.strip(), confidence=_coerce_confidence(data.get("confidence"))
        )

    def generate_message(self, context: MessageGenerationContext) -> str:
        system = (
            "You are the message-drafting component of Bridge AI, a workplace communication "
            "agent that reaches out to stakeholders on behalf of a case that needs their "
            "input. Write ONLY the message body — no subject line, no JSON, no markdown, no "
            "commentary about what you're doing or who you are. Keep it concise, "
            "professional, and specific to the case. Match tone to the channel: email may be "
            "slightly more formal; telegram should be short and direct."
        )
        user = (
            f"Channel: {context.channel}\n"
            f"Recipient: {context.recipient_name}\n"
            f"Topic: {context.topic or 'unclassified'}\n"
            f"Missing stakeholders still needed: {', '.join(context.missing_roles) or 'none'}\n"
            f"Case summary: {context.case_summary}\n\n"
            "Write the message now."
        )
        content = self._call_with_retry(system=system, user=user, json_mode=False)
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
        if not text:
            raise LLMResponseError("Featherless returned an empty generated message")
        return text

    # --- request plumbing --------------------------------------------------------------------

    def _complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        content = self._call_with_retry(system=system, user=user, json_mode=True)
        return self._parse_json(content)

    def _call_with_retry(self, *, system: str, user: str, json_mode: bool) -> str:
        max_retries = self._settings.llm_max_retries
        backoff = self._settings.llm_retry_backoff_seconds
        attempt = 0

        while True:
            try:
                return self._call_once(system=system, user=user, json_mode=json_mode)
            except (APIConnectionError, APITimeoutError) as exc:
                reason = type(exc).__name__
            except APIStatusError as exc:
                if exc.status_code not in _RETRYABLE_STATUS_CODES:
                    # Never expose the API key: only the status code and error type are
                    # logged/raised, never the raw exception (which could echo request state).
                    raise LLMRequestError(
                        f"Featherless request failed with non-retryable HTTP {exc.status_code}"
                    ) from None
                reason = f"HTTP {exc.status_code}"

            if attempt >= max_retries:
                raise LLMTransientError(
                    f"Featherless request failed after {attempt + 1} attempt(s): {reason}"
                ) from None

            sleep_for = backoff * (2**attempt)
            attempt += 1
            logger.warning(
                "Featherless transient failure (%s) — retrying attempt %d/%d in %.1fs",
                reason,
                attempt,
                max_retries,
                sleep_for,
            )
            time.sleep(sleep_for)

    def _call_once(self, *, system: str, user: str, json_mode: bool) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._settings.llm_temperature,
            "max_tokens": self._settings.llm_max_tokens,
        }

        if json_mode and self._supports_json_mode:
            try:
                response = self._client.chat.completions.create(
                    response_format={"type": "json_object"}, **kwargs
                )
                return response.choices[0].message.content or ""
            except BadRequestError:
                # Part 3's fallback: this model/endpoint doesn't support the structured-output
                # mechanism. Fall back to prompt-only JSON (the system prompt already asks for
                # it explicitly) for this call and every one after it.
                logger.warning(
                    "Featherless model '%s' rejected response_format=json_object — falling "
                    "back to prompt-only JSON instructions for the rest of this process.",
                    self._model,
                )
                self._supports_json_mode = False

        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise LLMResponseError("Featherless returned an empty response")

        for candidate in (text, *_json_candidates(text)):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        raise LLMResponseError(
            f"Featherless response was not valid JSON (first 200 chars): {text[:200]!r}"
        )


def _json_candidates(text: str) -> list[str]:
    """Fallback extraction strategies tried, in order, when the raw response isn't itself
    parseable JSON — a model asked for "ONLY JSON" sometimes still wraps it in a markdown
    fence or adds a stray sentence before/after. Never used to *invent* structure, only to
    strip surrounding noise around what is still expected to be a real JSON object.
    """
    candidates: list[str] = []
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        candidates.append(fence_match.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    return candidates


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise LLMResponseError(f"'confidence' must be a number, got {value!r}")
    score = float(value)
    if 1.0 < score <= 100.0:
        score /= 100.0  # tolerate a model that used a 0-100 scale instead of 0-1
    return max(0.0, min(1.0, score))


def _coerce_str_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise LLMResponseError(f"'{field}' must be a JSON array, got {value!r}")
    if not all(isinstance(item, str) for item in value):
        raise LLMResponseError(f"'{field}' must be an array of strings, got {value!r}")
    return tuple(value)
