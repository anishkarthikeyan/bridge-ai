"""Postgres checkpointer wiring — LangGraph's PostgresSaver, backed by the same PostgreSQL
instance as everything else (Settings.database_url), so there is no second stateful system
to run for the AI Brain's own persistence.

This is what makes "the graph must survive process restarts, machine restarts, and
multi-day reply delays" true: every checkpoint — including every wait_for_reply pause — is
written to Postgres before `compiled_graph.invoke(...)` returns, so a brand new process,
pointed at the same database with no in-memory state carried over, can resume a case exactly
where it left off via the same thread_id. Verified end to end, including a simulated process
restart across two separate OS processes, during this build.

`_ALLOWED_STATE_TYPES` below is deliberate, not `allowed_msgpack_modules=True` left alone:
AgentState nests our own domain dataclasses and enums (Priority, Channel, PolicyTopic, ...),
and LangGraph's default serializer only natively trusts a small set of built-in types —
anything else falls back to a pickle-based extension encoding. Passing `True` allows that
for *any* type but still logs "this will be blocked in a future version" on every single
read, because `True` means "allow everything, with a warning," not "allow silently." The
fallback exists to stop a checkpoint store from deserializing arbitrary attacker-controlled
classes; it doesn't apply here — the checkpoint store is our own Postgres database, and
everything in it is state *we* wrote — so the correct fix is an explicit allowlist of
exactly the types AgentState can nest, audited against brain/state.py, not a blanket
allow-with-warning. Re-audited and verified warning-free across a real cross-process resume
during Phase 6 (Phase 4's original audit missed the two types RoleResolver added in Phase 5,
since Phase 5 never re-ran the real-Postgres check — only InMemorySaver-backed tests, which
don't exercise this serializer at all); add a type here the moment a new field type is added
anywhere under AgentState, and re-verify against a real Postgres checkpointer, not just
InMemorySaver, whenever one is.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import dict_row

from app.infrastructure.config import get_settings

_ALLOWED_STATE_TYPES: set[tuple[str, str]] = {
    ("app.brain.state", "ConversationGraphState"),
    ("app.brain.state", "ParticipantState"),
    ("app.application.dto.inbound_message", "InboundMessage"),
    ("app.application.dto.inbound_message", "MessageParticipant"),
    ("app.application.ports.llm_port", "IntentResult"),
    ("app.application.ports.llm_port", "EntitiesResult"),
    ("app.application.ports.llm_port", "TopicClassification"),
    ("app.domain.value_objects.policy_pack", "PolicyTopic"),
    ("app.domain.value_objects.policy_pack", "EscalationRules"),
    ("app.domain.value_objects.policy_pack", "CommunicationRules"),
    ("app.domain.value_objects.channel", "Channel"),
    ("app.domain.value_objects.communication_health", "CommunicationHealth"),
    ("app.domain.value_objects.priority", "Priority"),
    ("app.domain.value_objects.resolution_state", "ResolutionState"),
    ("app.domain.value_objects.candidate_contact", "CandidateContact"),
    ("app.domain.value_objects.role_resolution", "RoleResolution"),
    ("app.domain.value_objects.decision_status", "DecisionStatus"),
    ("app.domain.value_objects.resolution_outcome", "ResolutionOutcome"),
}


def _psycopg_conn_string(database_url: str) -> str:
    """PostgresSaver talks to psycopg directly, not through SQLAlchemy — it wants a plain
    `postgresql://` DSN, not SQLAlchemy's `postgresql+psycopg[2]://` dialect syntax."""
    return database_url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


@contextmanager
def postgres_checkpointer(database_url: str | None = None) -> Iterator[PostgresSaver]:
    """Yields a ready-to-use PostgresSaver with its tables created — `.setup()` is
    idempotent, safe to call on every process start. `database_url` defaults to
    Settings.database_url; overridable so tests can point at a throwaway database.
    """
    conn_string = _psycopg_conn_string(database_url or get_settings().database_url)
    serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_STATE_TYPES)

    with Connection.connect(
        conn_string, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        checkpointer = PostgresSaver(conn, serde=serde)
        checkpointer.setup()
        yield checkpointer
