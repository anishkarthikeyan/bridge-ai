# Bridge AI

Bridge AI is an autonomous communication orchestration agent that detects missing
stakeholders, evaluates communication health, and reaches the right people across
communication channels — built for the **Caspian Buildathon**.

## The problem

Teams often already have the information required to move something forward, but the right
stakeholders simply aren't in the conversation. A payment change ships without Security
signing off. A migration goes out without QA in the loop. Nobody decided to skip them — the
thread just never reached them.

Bridge AI watches a conversation, works out who *should* be in it based on organizational
policy, and — when they're missing — reaches them on whichever channel actually works,
autonomously follows up, escalates when it has to, and keeps every message attached to the
same case until it's resolved.

## Demo

Verified live, end to end, against the real Caspian API, real Postgres, and a real LLM. A
real Telegram message:

> "Payment of ₹25,000 is stuck and Finance and Security haven't reviewed it yet."

drove the full pipeline:

1. Caspian delivered the Telegram event to Bridge AI's inbound poller.
2. Intent detected as an escalation request.
3. Topic classified as `payment_system`.
4. The payment-system policy loaded — requires Finance, Security, and Support.
5. Finance, Security, and Support all identified as missing from the thread.
6. Communication health calculated.
7. Priority calculated as high.
8. The resolution evaluator decided the case required escalation.
9. A real stakeholder was resolved for the missing role.
10. Bridge AI drafted an email addressed to them.
11. The email was dispatched through Caspian — for real.
12. The case, its decisions, and the full reasoning timeline were persisted to Postgres and
    rendered in the React frontend.

**Telegram and Email are the two channels demonstrated end to end** in this build — inbound
via Telegram, outbound stakeholder resolution via Email, both through Caspian.

## Key features

**Intelligent message understanding** — intent detection, entity extraction, and topic
classification, each a single scoped LLM call against a real Featherless-hosted model.

**Stakeholder intelligence** — required roles are policy-driven (per topic, not hardcoded),
missing stakeholders are detected deterministically, and a missing role is resolved to an
actual reachable person and channel.

**Communication health & priority** — a deterministic health score and priority calculation
feed a single resolution decision point: wait, follow up, escalate, or resolve. Never the LLM.

**Autonomous escalation** — priority is raised, the right stakeholder is targeted, a message
is drafted for them specifically, and it's dispatched — with no human in the loop.

**Case continuity across channels** — a reply on an already-open conversation resumes the
same case rather than forking a new one, whether it lands on the original channel or a new
one Bridge AI escalated to.

**Persistent case management** — cases, decisions (a full audited reasoning trail),
conversations, and participants all live in Postgres and survive process restarts, including
mid-conversation, via a real LangGraph checkpoint.

**Autonomous follow-up** — a background scheduler re-evaluates cases whose cooldown has
expired with no new reply, using the exact same deterministic reasoning nodes as a real
message pass.

**Frontend case dashboard** — a case list and a live case detail view (status, priority,
health, missing stakeholders, channels, and a chronological decision timeline), polling the
backend's read API.

## Architecture

```mermaid
flowchart TD
    TG[Telegram]
    EM_IN[Email inbound]
    C[Caspian]
    POLL[CaspianInboundPoller]
    HANDLER[BridgeAgentHandler]
    USECASE[IngestInboundMessageUseCase]
    GRAPH[LangGraph reasoning pipeline]
    LLM[Featherless LLM]
    DB[(PostgreSQL)]
    EMAIL_OUT[Email outbound]
    UI[React frontend]
    API[FastAPI read API]

    TG --> C
    EM_IN --> C
    C -->|poll every 5s| POLL
    POLL --> HANDLER
    HANDLER --> USECASE
    USECASE --> GRAPH
    GRAPH <--> LLM
    GRAPH --> DB
    GRAPH -->|dispatch| C
    C --> EMAIL_OUT
    DB --> API
    API --> UI
```

Inside the reasoning pipeline, every case runs a fixed LangGraph node sequence — intent
extraction, entity extraction, topic classification, policy lookup, missing-stakeholder
detection, communication health, priority, and a single deterministic resolution decision
that routes to follow-up, escalation, or resolution. See
**[docs/architecture.md](docs/architecture.md)** for the full node-by-node breakdown, the
clean-architecture layer boundaries, and two non-obvious persistence-layer fixes made during
development.

## Technology stack

**Backend** — Python 3.12, FastAPI, LangGraph, SQLAlchemy, Alembic, PostgreSQL, Pydantic
Settings, [caspian-sdk](https://pypi.org/project/caspian-sdk/), APScheduler.

**AI** — Featherless (OpenAI-compatible API), DeepSeek-V3.2, used for exactly four scoped
tasks: intent extraction, entity extraction, topic classification, and message drafting.
Every other decision in the pipeline is deterministic.

**Frontend** — React 19, TypeScript, Vite, Tailwind CSS, React Router, lucide-react.

**Infrastructure** — Docker, Docker Compose, uv (Python packaging), pnpm.

**Testing & quality** — pytest, ruff, mypy (strict), oxlint.

## Project structure

```
app/
  domain/            entities, value objects, deterministic reasoning services
  application/        use cases + ports (interfaces integrations implement)
  brain/               LangGraph nodes, graph wiring, Postgres checkpointer
  integrations/        Caspian client/adapters, Featherless client, SQLAlchemy repositories
  infrastructure/       config, DB engine, DI composition root, schedulers
  main.py               FastAPI app factory + lifespan wiring
frontend/              React app (its own README: frontend/README.md)
migrations/            Alembic schema migrations
policies/               topic → required-roles rules, role directory (YAML)
examples/               canonical demo scenarios (JSON)
tests/                  unit + integration test suite
docs/                   architecture.md — deeper technical detail
scripts/                small operational/verification scripts
```

## Quick start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and [pnpm](https://pnpm.io/)
- PostgreSQL 16 (native, or via Docker — see [Database](#database) below)
- A [Caspian](https://trycaspianai.com) API key (for real inbound/outbound messaging)
- A [Featherless](https://featherless.ai) API key (for real LLM calls)

Without Caspian/Featherless credentials the app still starts — it falls back to a local
in-process client for Caspian and needs an LLM key to run reasoning; see
[Environment](#environment).

### Clone

```bash
git clone https://github.com/anishkarthikeyan/bridge-ai.git
cd bridge-ai
```

### Backend

```bash
uv sync
```

### Environment

```bash
cp .env.example .env
```

Fill in `DATABASE_URL` (or the individual `POSTGRES_*` values it's built from),
`FEATHERLESS_API_KEY`, and `CASPIAN_API_KEY` at minimum. Every variable is documented inline
in `.env.example`, and read exclusively through `app/infrastructure/config.py` — nothing in
the app reads `os.environ` directly.

### Database

```bash
# Point DATABASE_URL at any reachable Postgres 16 — a local native install, or:
docker compose up -d db

uv run alembic upgrade head
```

See [Docker & database setup](#docker--database-setup) below for how the two Postgres options
relate to each other.

### Frontend

```bash
cd frontend
pnpm install
```

### Run

```bash
# Backend (from the repo root)
uv run bridge-ai
# or: uv run uvicorn app.main:app --reload

# Frontend (from frontend/, separate terminal)
pnpm dev
```

Then check:

```bash
curl localhost:8000/health
# {"status":"ok"}
```

and open the frontend dev server's printed URL (defaults to `http://localhost:5173`).

## Docker & database setup

`docker-compose.yml` defines two services: `db` (PostgreSQL) and `app` (the backend,
containerized). Development on this project has been running the backend natively against a
**native PostgreSQL install on `localhost:5432`**, configured via `.env`'s `DATABASE_URL` —
that's the authoritative database for local development, and it's what `uv run bridge-ai`
and `uv run alembic upgrade head` talk to by default.

Docker's `db` service exists for containerized/local deployment (`docker compose up`), not as
a second copy of your development data. Its **host-side** port is published on `5433`, not
`5432` — specifically so it never contends with a native Postgres install already using
`5432` on the same machine. This only affects host tools (`psql`, a locally-run
`bridge-ai`) connecting from outside Docker; **inside** the compose network, `app` always
reaches `db` as `db:5432` (the container's own port), regardless of what's published to the
host — see the `app.environment.DATABASE_URL` override in `docker-compose.yml`.

If you want a fully clean environment without touching whatever database your `.env` already
points at:

```bash
docker compose up -d db
DATABASE_URL=postgresql+psycopg://bridge_ai:bridge_ai@localhost:5433/bridge_ai uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://bridge_ai:bridge_ai@localhost:5433/bridge_ai uv run bridge-ai
```

This spins up a fresh, empty, fully-migrated database on port 5433 and points the backend at
it for that run only — your native Postgres data is never read or written.

## Caspian integration

[Caspian](https://trycaspianai.com) is Bridge AI's communication layer — every inbound and
outbound message, on every channel, goes through it. Nothing talks to Telegram or an SMTP
server directly.

- **Telegram** provides inbound communication — a real user messaging the connected bot.
- **Email** is used for stakeholder outreach — Bridge AI drafts and dispatches through
  Caspian's email channel when it resolves a missing stakeholder or replies to a thread.
- `app/infrastructure/caspian_poller.py` polls Caspian's event API on an interval
  (`CASPIAN_INBOUND_POLL_INTERVAL_SECONDS`, default 5s) and hands every event to the single
  registered handler.
- That one handler (`BridgeAgentHandler`) is the only Caspian-registered entrypoint,
  regardless of channel — see `app/integrations/inbound/caspian_handler.py`.
- Outbound dispatch always goes through `DispatchMessageUseCase` →
  `CaspianGateway` → the real `caspian-sdk` client — never a parallel send path.

Required environment variables (see `.env.example` for the full, current list):

```
CASPIAN_API_KEY=
CASPIAN_BASE_URL=https://api.trycaspianai.com
CASPIAN_EMAIL_USERNAME=
TELEGRAM_BOT_TOKEN=
```

`CASPIAN_API_KEY` left blank falls back to an in-process local client (the same one the test
suite uses) rather than failing startup — useful for running the app without real credentials
configured. `TELEGRAM_BOT_TOKEN` is only needed to *create* a new Telegram connection; if
Caspian already owns one, Bridge AI discovers and reuses it.

## Example workflow

```
User (Telegram): "Payment of ₹25,000 is stuck and Finance and Security haven't reviewed it
yet. Please escalate this."
```

1. Caspian delivers the Telegram event to Bridge AI's inbound poller.
2. Bridge AI classifies the intent as an escalation request.
3. The topic is classified as `payment_system`.
4. The payment-system policy requires Finance, Security, and Support.
5. All three are identified as missing from the conversation.
6. Communication health is calculated from the conversation's state.
7. Priority is calculated as high.
8. The resolution evaluator determines the case requires escalation.
9. The missing stakeholder is resolved to a real contact and channel.
10. Bridge AI drafts a message addressed to them specifically.
11. Caspian dispatches it through Email.
12. The case timeline records every decision above, in order, and the frontend renders it.

This is the demonstrated workflow, not a hypothetical — see [Demo](#demo).

## Testing

```bash
uv run pytest          # full suite
uv run ruff check .    # lint
uv run mypy app        # type check (strict)
```

Current result on this build: **141 tests, 140 passing reliably; one live end-to-end test
(`test_caspian_real_end_to_end.py`) depends on a real, rate-limited Featherless API call and
is intermittently `HTTP 429`'d under heavy quota usage — confirmed to pass cleanly in
isolation.** This is an external rate limit, not an application defect, and the test is not
altered to hide it.

Most of the suite needs no live services at all. Tests that do call a real database, Caspian,
or Featherless are marked to **skip cleanly** (not fail) when the corresponding credentials or
a reachable Postgres aren't configured — `pytest.mark.skipif` guards on `DATABASE_URL`
connectivity, `CASPIAN_API_KEY`, and `FEATHERLESS_API_KEY` throughout `tests/integration/`.
Running `uv run pytest` with a bare `.env` (no real credentials) still exercises the full unit
suite and the deterministic parts of the integration suite.

## Security

- All credentials are supplied through environment variables, read once through
  `app/infrastructure/config.py` — nothing in the application reads `os.environ` directly.
- `.env` is git-ignored; `.env.example` contains variable names and safe placeholders only.
- No secrets are committed to this repository or its history (verified during cleanup).
- This is a hackathon build, not a hardened production deployment — for real production use,
  credentials should come from a proper secret manager, and any exposed database or API
  credentials should be rotated.

## Known limitations

- **Message persistence** — inbound message content is processed through the full agent
  workflow (intent, entities, topic, and everything downstream all see the real text), but
  the current implementation does not persist every inbound `Message` row into the `messages`
  table. `Case`, `Conversation`, `Participant`, and `Decision` records are all real and
  durable; this is specifically about the raw per-message audit log.
- **Two demonstrated channels** — Telegram (inbound) and Email (outbound) are verified end to
  end. Slack and Discord are recognized as channel values in the domain model but have no
  adapter implementation yet.
- **Single-process scheduling** — the follow-up sweep and Caspian poller are in-process
  APScheduler jobs, not a distributed queue; this matches the scope of a single-instance
  hackathon deployment.

## Roadmap

- Persist every inbound `Message` row, not just the derived case/decision state.
- Additional communication channels (Slack, Discord).
- Stronger observability (structured tracing across the reasoning pipeline).
- Production-grade secret management for deployment.
- Background worker separation from the API process.
- Richer stakeholder directory integration beyond the static YAML role directory.

## License

Released under the [MIT License](LICENSE).
