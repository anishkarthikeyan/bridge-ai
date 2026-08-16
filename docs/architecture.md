# Architecture

This document goes one level deeper than the root [README](../README.md)'s overview — the
actual layers, the actual LangGraph node sequence, and the handful of non-obvious design
decisions that shaped them.

## Layers

The backend follows clean architecture: dependencies only ever point inward.

```
app/
  domain/          entities, value objects, and the deterministic reasoning services
                    (StakeholderEngine, CommunicationHealthCalculator, PriorityEngine,
                    ResolutionEvaluator, ChannelRegistry, RoleResolver, ...). No framework
                    imports — nothing here knows FastAPI, SQLAlchemy, or LangGraph exist.

  application/      use cases (DispatchMessageUseCase, IngestInboundMessageUseCase,
                    EvaluateCaseUseCase, RunFollowupSweepUseCase) and the ports they depend
                    on (CaseRepositoryPort, LLMPort, ChannelPort, ...) — interfaces only.
                    Depends on domain, nothing else.

  brain/            the LangGraph reasoning engine: node implementations, the compiled graph,
                    the Postgres checkpointer, and AgentState. Every node is a thin adapter
                    around a domain service or a use case — no business rules live here that
                    don't already live in domain/.

  integrations/     concrete adapters: the real Caspian client and channel adapters
                    (inbound), the Caspian gateway (outbound), the Featherless LLM client,
                    and the SQLAlchemy repositories (persistence). Implements the ports
                    application/ defines; never imported by domain/ or application/.

  infrastructure/   configuration, the DB engine/session factory, the DI composition root,
                    logging, and the two background schedulers (follow-up sweep, Caspian
                    inbound poll).

  main.py           FastAPI app factory + lifespan wiring — the one place that assembles a
                    Container, opens the checkpointer, registers the one Caspian handler, and
                    starts both schedulers.
```

`migrations/` (Alembic), `policies/` (YAML topic → required-roles rules and the role
directory), `examples/` (canonical demo scenarios as JSON), and `tests/` sit alongside `app/`
at the repo root. `frontend/` is a separate, independently-run React app (see its own
[README](../frontend/README.md)) that only ever talks to the backend's read API.

## The reasoning pipeline (LangGraph)

Every case, every pass, runs the same fixed sequence before the one decision point:

```
receive_message → extract_intent → extract_entities → classify_topic → load_policy
  → detect_missing_stakeholders → calculate_communication_health → calculate_priority
  → resolution_evaluator
```

Four of those nine nodes call the LLM (`extract_intent`, `extract_entities`,
`classify_topic`, and later `generate_message`) — every other node, including the ones that
follow, is deterministic. `resolution_evaluator` is the *only* branch point, returning
exactly one of `WAIT / FOLLOW_UP / ESCALATE / RESOLVED` from missing roles, communication
health, the last dispatch's outcome, attempt count, and the policy pack's thresholds — never
the LLM:

```
resolution_evaluator
  ├── WAIT       → wait_for_reply                (pause; nothing to send this pass)
  ├── FOLLOW_UP  → select_channel → generate_message → create_decision → dispatch → wait_for_reply
  ├── ESCALATE   → escalate → select_channel → ... → dispatch → wait_for_reply
  └── RESOLVED   → resolve_case → END
```

`escalate` doesn't duplicate the send pipeline — it just raises priority to `HIGH` and
reorders `missing_roles` to put the policy pack's escalation targets first, then hands off to
the same `select_channel` every other path uses. `select_channel` itself has two paths: if a
role is missing, `RoleResolver` resolves it to a real person and a channel in one step; if
not (or resolution fails), it falls back to a priority → communication-style → channel-rules
chain addressing whoever sent the current message. Every node persists exactly one `Decision`
row (the audit trail) and the case's updated state before returning, via a lifecycle enforced
structurally by `BrainNode.__call__` — a node cannot skip persistence even if it wanted to.

`wait_for_reply` is the checkpoint pause — a real LangGraph `interrupt()`, durable in
Postgres, that survives process restarts. A reply resumes the exact same node sequence from
`receive_message`; `EvaluateCaseUseCase` (used by the autonomous follow-up scheduler) runs the
same node classes directly, starting from `load_policy`, for the no-new-message case.

## Persistence

`Case` is the aggregate root: participants, conversations (one per channel thread), messages,
and decisions all hang off it. A `Conversation` is what makes cross-channel continuity work —
when a reply arrives on a channel/thread already registered to an open case,
`find_by_conversation_ref` resumes that case instead of opening a new one; a successful
dispatch to a *new* recipient registers its own conversation the same way, so a later reply on
that thread resumes correctly too.

Two real engineering fixes worth knowing about if you're reading the code, both scoped to the
persistence boundary rather than any business logic:

- **Session-per-inbound-event.** The Caspian inbound path (poller → handler → use case →
  graph) now opens a fresh SQLAlchemy session per event, commits on success, rolls back and
  re-raises on failure, and always closes — the same unit-of-work discipline the follow-up
  scheduler already used. See `_SessionPerEventInboundRouter` in `app/main.py`.
- **UTC session pinning.** Every timestamp column is timezone-naive; a PostgreSQL session
  whose ambient timezone isn't UTC silently shifts what gets written. `app/infrastructure/db.py`
  pins every connection's session to `TIME ZONE 'UTC'` on connect, so the read-side
  `_as_utc()` label (in the repositories) is actually true rather than assumed.

## Known limitation

Inbound message *content* drives the full reasoning pipeline (intent, entities, topic, and
everything downstream all see the real text), but individual `Message` rows are not currently
persisted into the `messages` table — `MessageRepositoryPort` exists but isn't wired into any
node yet. `Case`, `Conversation`, `Participant`, and `Decision` rows are all real and durable;
this is specifically about the raw per-message audit log. See the README's
[Known Limitations](../README.md#known-limitations).
