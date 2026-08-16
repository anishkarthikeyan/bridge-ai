"""Phase 4 — Decision.executed (bool) replaced by Decision.status (enum lifecycle)

Revision ID: 0143190572b5
Revises: 2e4fda3836d9
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0143190572b5"
down_revision: str | None = "2e4fda3836d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decisions", sa.Column("status", sa.String(), nullable=False, server_default="pending")
    )
    # Backfill: a decision that was already marked executed=True has succeeded; anything
    # still False was never carried out, i.e. still pending. No EXECUTING/FAILED history to
    # recover — those states didn't exist before this migration.
    op.execute("UPDATE decisions SET status = 'success' WHERE executed = true")
    op.create_index("ix_decisions_status", "decisions", ["status"])

    op.drop_index("ix_decisions_executed", table_name="decisions")
    op.drop_column("decisions", "executed")


def downgrade() -> None:
    op.add_column(
        "decisions", sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.execute("UPDATE decisions SET executed = true WHERE status = 'success'")
    op.create_index("ix_decisions_executed", "decisions", ["executed"])

    op.drop_index("ix_decisions_status", table_name="decisions")
    op.drop_column("decisions", "status")
