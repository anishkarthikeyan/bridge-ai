"""No abstract SchedulerPort is defined here, deliberately (Phase 6.5).

`app/infrastructure/scheduler.py`'s `FollowupScheduler` is the only thing in this codebase
that schedules anything, nothing in `application/` or `domain/` depends on "a scheduler" as a
concept, and there is exactly one implementation (APScheduler) with no second one anywhere on
the roadmap — the same reasoning `app/infrastructure/logging.py` already applies (no
`LoggingPort` either). Introducing a port with a single, infrastructure-only implementer
would be indirection with no caller on the other side of it; see `CaseRepositoryPort` and
`LLMPort` for what an interface earns its place here by (multiple real implementations: SQL +
in-memory fakes, Featherless + FakeLLMPort).

If a second scheduling backend is ever needed, extract the port then, from
`FollowupScheduler`'s actual public surface (`start()` / `shutdown()`) — not speculatively now.
"""
