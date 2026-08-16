"""Phase 2 core persistence models — Case, Participant, Conversation, Message, Decision, Policy

Revision ID: ce7d65fb65a9
Revises:
Create Date: 2026-08-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ce7d65fb65a9"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(), nullable=True),
        sa.Column("required_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("channels_used", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("communication_health", sa.String(), nullable=False),
        sa.Column("resolution_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cases_topic", "cases", ["topic"])
    op.create_index("ix_cases_communication_health", "cases", ["communication_health"])
    op.create_index("ix_cases_resolution_status", "cases", ["resolution_status"])

    op.create_table(
        "participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("telegram_handle", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_participants_case_id", "participants", ["case_id"])
    op.create_index("ix_participants_role", "participants", ["role"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("external_thread_ref", sa.String(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_case_id", "conversations", ["case_id"])
    op.create_index("ix_conversations_channel", "conversations", ["channel"])
    op.create_index(
        "ix_conversations_external_thread_ref", "conversations", ["external_thread_ref"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_participant_id", sa.Uuid(), nullable=True),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("external_message_ref", sa.String(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sender_participant_id"], ["participants.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_direction", "messages", ["direction"])
    op.create_index("ix_messages_external_message_ref", "messages", ["external_message_ref"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.Column("chosen_action", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_case_id", "decisions", ["case_id"])
    op.create_index("ix_decisions_node_name", "decisions", ["node_name"])
    op.create_index("ix_decisions_created_at", "decisions", ["created_at"])

    op.create_table(
        "policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("industry_pack", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("required_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "industry_pack", "topic", "version", name="uq_policy_pack_topic_version"
        ),
    )
    op.create_index("ix_policies_industry_pack", "policies", ["industry_pack"])
    op.create_index("ix_policies_topic", "policies", ["topic"])
    op.create_index("ix_policies_is_active", "policies", ["is_active"])


def downgrade() -> None:
    op.drop_table("policies")
    op.drop_table("decisions")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("participants")
    op.drop_table("cases")
