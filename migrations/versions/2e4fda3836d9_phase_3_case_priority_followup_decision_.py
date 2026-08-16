"""Phase 3 — Case priority/follow-up fields, Decision execution state

Revision ID: 2e4fda3836d9
Revises: ce7d65fb65a9
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2e4fda3836d9"
down_revision: str | None = "ce7d65fb65a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Case: autonomous follow-up state (survives process restarts and delayed replies) +
    # priority (deterministic channel selection depends on it — Phase 3 reasoning layer).
    op.add_column(
        "cases", sa.Column("priority", sa.String(), nullable=False, server_default="medium")
    )
    op.add_column(
        "cases", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("cases", sa.Column("next_check_at", sa.DateTime(), nullable=True))
    op.create_index("ix_cases_priority", "cases", ["priority"])
    op.create_index("ix_cases_next_check_at", "cases", ["next_check_at"])

    # Decision: execution state, separate from the decision having been recorded — retries,
    # replay, and dashboard visualization all key off this.
    op.add_column(
        "decisions",
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_decisions_executed", "decisions", ["executed"])


def downgrade() -> None:
    op.drop_index("ix_decisions_executed", table_name="decisions")
    op.drop_column("decisions", "executed")

    op.drop_index("ix_cases_next_check_at", table_name="cases")
    op.drop_index("ix_cases_priority", table_name="cases")
    op.drop_column("cases", "next_check_at")
    op.drop_column("cases", "attempt_count")
    op.drop_column("cases", "priority")
