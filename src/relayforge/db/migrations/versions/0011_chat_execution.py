from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0011_chat_execution"
down_revision = "0010_attachments"
branch_labels = None
depends_on = None


DEPENDENTS = ("job_steps", "events", "artifacts", "findings", "approvals", "approval_grants")


def _preserve_dependents() -> list[tuple[sa.Table, list[dict[str, Any]]]]:
    # SQLite batch rebuild drops the parent. Its ON DELETE CASCADE still
    # applies with foreign_keys enabled. Copy affected children before that
    # operation and restore their original keys in dependency order.
    connection = op.get_bind()
    metadata = sa.MetaData()
    result = []
    for name in DEPENDENTS:
        table = sa.Table(name, metadata, autoload_with=connection)
        result.append((table, [dict(row) for row in connection.execute(sa.select(table)).mappings()]))
    return result


def _restore_dependents(saved: list[tuple[sa.Table, list[dict[str, Any]]]]) -> None:
    from sqlalchemy.dialects.sqlite import insert

    for table, rows in saved:
        if rows:
            op.get_bind().execute(insert(table).on_conflict_do_nothing(), rows)
    if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("Migration foreign key integrity failure")


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("next_event_seq", sa.Integer(), nullable=False, server_default="1")
    )
    op.execute(
        "UPDATE conversations SET next_event_seq = (SELECT COALESCE(MAX(seq), 0) + 1 "
        "FROM events WHERE events.conversation_id = conversations.id)"
    )
    saved = _preserve_dependents()
    with op.batch_alter_table(
        "jobs", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
    ) as batch:
        batch.drop_constraint("uq_jobs_conversation_id", type_="unique")
        batch.add_column(sa.Column("review_only", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("origin_message_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("origin_turn_id", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("planner_session_established", sa.Integer(), nullable=False, server_default="0")
        )
    _restore_dependents(saved)
    op.execute(
        "UPDATE jobs SET planner_session_established = "
        "(SELECT session_established FROM conversations WHERE conversations.id = jobs.conversation_id)"
    )
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.String(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("tool_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pid", sa.Integer()),
        sa.Column("pid_create_time", sa.Float()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String()),
    )
    op.create_index("ix_chat_turns_conversation_id", "chat_turns", ["conversation_id"])
    op.create_table(
        "chat_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_id", sa.String(), sa.ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("resource_path", sa.Text(), nullable=False),
        sa.Column("operation_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decision_key", sa.String(), unique=True),
        sa.Column("result_json", sa.Text()),
        sa.Column("pid", sa.Integer()),
        sa.Column("pid_create_time", sa.Float()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String()),
    )
    op.create_index("ix_chat_actions_conversation_id", "chat_actions", ["conversation_id"])


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT conversation_id FROM jobs "
            "GROUP BY conversation_id HAVING COUNT(*) > 1)"
        )
    )
    if count:
        raise RuntimeError("Downgrade refused: several Jobs share a conversation; preserve data.")
    op.drop_table("chat_actions")
    op.drop_table("chat_turns")
    saved = _preserve_dependents()
    with op.batch_alter_table("jobs") as batch:
        batch.create_unique_constraint("uq_jobs_conversation_id", ["conversation_id"])
        batch.drop_column("review_only")
        batch.drop_column("origin_message_id")
        batch.drop_column("origin_turn_id")
        batch.drop_column("planner_session_established")
    _restore_dependents(saved)
    op.execute("ALTER TABLE conversations DROP COLUMN next_event_seq")
