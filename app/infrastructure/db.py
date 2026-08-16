"""SQLAlchemy engine and session factory.

This is the one place that talks to `DATABASE_URL` directly. Adapters and the DI container
depend on it; the domain and application layers never import it — they depend only on
`CaseRepositoryPort` and friends (see app/application/ports/).

Timezone normalization (persistence boundary, not a schema or business-logic change): every
timestamp column on every model (models.py's `created_at`, `updated_at`, `next_check_at`,
`joined_at`, `opened_at`, `sent_at`, ...) is a plain `TIMESTAMP WITHOUT TIME ZONE` — untyped
`Mapped[datetime]` maps to that by default, and changing it to `DateTime(timezone=True)`
would be a real schema change, which is explicitly out of scope here. A naive column has no
timezone of its own; what it actually stores depends entirely on the PostgreSQL *session's*
`TimeZone` setting at write time, and libpq sessions default to the client OS's local
timezone unless told otherwise (confirmed empirically on this deployment: `SHOW timezone`
returns `Asia/Kolkata` on a fresh, unconfigured connection). Two consequences, both
reproduced directly against real Postgres before this fix:

  1. `server_default=func.now()` columns: Postgres computes `now()` (a `timestamptz`) and
     casts it to the naive column *in the session's timezone* — so under an Asia/Kolkata
     session, a row created at 04:07 UTC has its naive `created_at` stored as `09:37`
     (local wall-clock digits, offset silently dropped from then on).
  2. Application-computed columns (e.g. `Case.next_check_at`, set from
     `datetime.now(UTC)` + a policy offset in app/domain/services/followup_policy.py):
     psycopg adapts the timezone-*aware* Python value for the wire, and Postgres applies the
     exact same session-timezone conversion on the way into the naive column — so even an
     already-correct UTC-aware value written by our own code gets the same +5:30 shift baked
     into what's actually stored.

Both are silently consistent with `app/integrations/persistence/sqlalchemy/repositories/
case_repository.py`'s (and message_repository.py's) `_as_utc()` helper, which reads a naive
value back and labels it `tzinfo=UTC` *without converting* — correct only on the assumption
that the naive value already represents true UTC wall-clock time. That assumption was false
under a non-UTC session; nothing on the read side needs to change once it's made true.

The fix: pin every connection this engine ever opens to a UTC session, once, at the
lowest possible layer — a `connect` event fires exactly once per new DBAPI connection
(pool_pre_ping validates and reuses pooled connections without re-firing it, which is
exactly what's wanted: set it once per physical connection, not once per checkout). This
changes nothing about column types (still naive `TIMESTAMP`, `\\d cases` is unchanged),
nothing about `FollowUpPolicy`/`ResolutionEvaluator`/any other domain service (all still
just compare `datetime.now(UTC)`-style aware values, unaware persistence ever entered the
picture), and nothing about any DTO or API response shape — it only makes the value actually
written match the value the read path has always assumed.
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.infrastructure.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every ORM model in adapters/persistence/sqlalchemy/models.py.

    Alembic's env.py imports this to build target_metadata for autogenerate.
    """


settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)


@event.listens_for(engine, "connect")
def _pin_session_timezone_to_utc(dbapi_connection: object, connection_record: object) -> None:
    """Runs once per new physical connection (see module docstring) — makes every naive
    `TIMESTAMP` column this engine ever writes or reads actually mean UTC, regardless of the
    server/OS's ambient session timezone default.

    Must commit explicitly: this fires before SQLAlchemy wraps the fresh DBAPI connection in
    any of its own transaction management, so `SET TIME ZONE` here runs inside an implicit
    transaction the DBAPI opened on our own `cursor.execute()` — left uncommitted, the very
    next `rollback()` anywhere on this connection (including SQLAlchemy's own
    `pool_reset_on_return` default, which rolls back on every checkin) reverts it to
    whatever the session's ambient default was, silently, for the rest of that pooled
    connection's lifetime. Verified directly: without this commit, a connection that merely
    rolled back once — completely unrelated to this setting — fell straight back to
    Asia/Kolkata for every later checkout. `SET TIME ZONE` (without `LOCAL`) is a session-
    level setting, not a schema or data change, so committing it here is exactly as durable
    and exactly as safe as never having started a transaction at all.
    """
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    try:
        cursor.execute("SET TIME ZONE 'UTC'")
        dbapi_connection.commit()  # type: ignore[attr-defined]
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a request-scoped session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
