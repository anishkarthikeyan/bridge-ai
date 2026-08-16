# Bridge AI

Autonomous, multi-channel communication agent — backend. Built for the Caspian Buildathon.

> Bridge AI's job is not to answer questions. It detects conversations that should exist but
> don't, and autonomously creates and drives those conversations — across email, Telegram,
> and whatever channel comes next — until the underlying issue is resolved.

The architecture is finalized (clean architecture, one Caspian handler, a persisted
Conversation Graph, a strict LLM/deterministic boundary). **The backend is feature-complete
as of Phase 6** — a case is received, reasoned about, dispatched, followed up, escalated, and
resolved end to end, with no LLM in the loop for anything but intent/entity extraction, topic
classification, and message text. What's left is the LLM integration itself, the frontend,
and deployment — see [What's not implemented yet](#whats-not-implemented-yet).

## Stack

Python 3.12 · FastAPI · LangGraph · PostgreSQL · SQLAlchemy · Alembic · Pydantic Settings ·
Featherless (OpenAI-compatible) · Caspian SDK · uv · Docker · pytest · ruff · mypy

## Layout

```
app/
  domain/           entities, value objects, the deterministic reasoning layer (services/) — no framework imports
  application/      use cases + ports (the interfaces integrations implement) + DTOs
  brain/            LangGraph reasoning engine — nodes, state, prompts ("the AI Brain")
  integrations/     inbound (Caspian handler, channel adapters), outbound, persistence, LLM, API
  infrastructure/   config, db, logging, DI composition root, scheduler
  main.py           FastAPI app factory + entrypoint
migrations/         Alembic
policies/           YAML config: software.yaml (topic -> required roles + rules),
                    role_directory.yaml (role -> candidate people)
examples/           official demo scenarios (JSON) — one inbound trigger + expected case shape
fixtures/           reserved for future test data
tests/              unit / integration / e2e
```

Every layer's dependency direction runs inward: `integrations` and `infrastructure` may
import `application` and `domain`; `application` may import `domain`; `domain` imports
nothing of ours. See the architecture doc for the full rationale.

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Docker (for Postgres, unless you point
`DATABASE_URL` at one you already have running).

```bash
cp .env.example .env

# Start Postgres only
docker compose up -d db

# Install dependencies (creates .venv, writes uv.lock on first run)
uv sync

# Run migrations — creates all 6 tables, adds Case.priority/attempt_count/next_check_at,
# then replaces Decision.executed (bool) with Decision.status (pending/executing/success/failed).
# No new migration in Phase 6 — its new state (ResolutionOutcome, pending_decision_id, ...)
# lives only in the LangGraph checkpoint, never in a table.
uv run alembic upgrade head

# Run the API
uv run bridge-ai
# or: uv run uvicorn app.main:app --reload
```

Check it's up:

```bash
curl localhost:8000/health
# {"status": "ok"}
```

### Running everything in Docker

```bash
docker compose up --build
```

### Tests, lint, types

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy app
```

### New migration

```bash
uv run alembic revision --autogenerate -m "add <table>"
uv run alembic upgrade head
```

## What's implemented (Phase 6 — the complete autonomous workflow)

Communication infrastructure (Phase 5), plus real termination — the backend is feature-complete:

- **`ResolutionEvaluator`** (`app/domain/services/resolution_evaluator.py`) — the one
  deterministic decision point after every reply is fully reprocessed. Never calls the LLM;
  returns exactly one of WAIT / FOLLOW_UP / ESCALATE / RESOLVED from missing roles,
  communication health, the last dispatch's status, attempt count, and policy-pack
  thresholds.
- **A real `END`** — `resolve_case` is the graph's only path to termination. The Phase 4/5
  unconditional `resume_case -> receive_message` loop is gone; a case now actually finishes.
- **`escalate`** — deterministic: bumps priority to HIGH and reorders `missing_roles` to
  target the policy pack's `escalation_rules.escalate_to_roles` first, then reuses
  `select_channel` unchanged — no duplicated send logic for the escalation path.
- **`dispatch` is a graph node now**, not a use case called manually after the graph pauses —
  `create_decision -> dispatch -> wait_for_reply` all run within the same pass, so a case's
  first message goes out for real before the graph ever pauses.
- **Three real bugs found and fixed during this phase's own verification**, not left latent:
  1. Nothing ever created a `Conversation` row, so `find_by_conversation_ref` (the
     find-or-resume-by-thread lookup relied on since Phase 1) could never actually find an
     existing case — every reply silently opened a second one. Fixed in `receive_message`.
  2. Two Phase 5 value objects (`CandidateContact`, `RoleResolution`) were never added to the
     checkpointer's type allowlist — invisible under `InMemorySaver`-only tests, only
     surfaced testing against real Postgres.
  3. `Case.next_check_at` (and every other persisted timestamp) comes back from Postgres
     timezone-naive, but every domain service compares timestamps against
     `datetime.now(UTC)` — fixed once, at the repository boundary, for every timestamp this
     app reads back, not at each comparison site.
- 21/21 tests pass, including dedicated coverage for all four `ResolutionEvaluator` branches,
  a structural "single `invoke()` call never runs unboundedly" guarantee, and — verified this
  session against a real Postgres instance across two independent OS processes — a case that
  survives a full process restart *and* reaches genuine termination (`resolution_status =
  resolved`, no further interrupt) in the second process.

## What's not implemented yet

- **LLM client** — `app/integrations/llm/featherless_client.py` is still a stub. Every brain
  node depends only on `LLMPort`, so wiring a real client in is additive, not a rewrite.
- **No retry/backoff policy on FAILED dispatch** — a failed send still drives a FOLLOW_UP
  retry via `ResolutionEvaluator`, but there's no backoff curve or max-failure ceiling
  distinct from the ordinary attempt-count/escalation thresholds.
- **App-lifecycle wiring** — `BridgeAgentHandler` is never registered from `main.py`; doing
  so needs a process-lifetime Session and checkpointer connection, which is FastAPI
  route/lifecycle wiring this build doesn't add (none was requested).
- **Scheduler** — `infrastructure/scheduler.py` is still a stub. `ResolutionEvaluator`'s WAIT
  outcome is designed for a periodic re-check with no new reply, but nothing calls the graph
  on a timer yet — every resume in this build is reply-triggered.
- **No cross-case view** — nothing lists/aggregates cases (e.g. "all cases past
  `next_check_at`"); `CaseRepositoryPort.list_open()` exists but nothing calls it yet.

What does work end to end, verified this session: a simulated Caspian inbound email drives
the full graph through real dispatch; a partial reply correctly escalates rather than just
waiting when the topic's policy calls for it; the reply that closes the last stakeholder gap
drives the case to `RESOLVED` and the graph actually terminates — and every one of those
steps survives a real process restart against a real Postgres checkpointer.
