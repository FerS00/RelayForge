import sqlalchemy as sa
from alembic import op

revision = "0012_previews"
down_revision = "0011_chat_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "previews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_id", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("argv_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("pid_create_time", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("log_path", sa.Text(), nullable=True),
        sa.Column("last_access_at", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_previews_conversation_status", "previews", ["conversation_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_previews_conversation_status", table_name="previews")
    op.drop_table("previews")
