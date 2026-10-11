import sqlalchemy as sa
from alembic import op

revision = "0014_desktop_targets"
down_revision = "0013_conversation_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_targets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_id", sa.String(), nullable=False),
        sa.Column("app", sa.String(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("pid_create_time", sa.Float(), nullable=False),
        sa.Column("hwnd", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("closed_at", sa.String(), nullable=True),
    )
    op.create_index("ix_desktop_targets_conversation_id", "desktop_targets", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_desktop_targets_conversation_id", table_name="desktop_targets")
    op.drop_table("desktop_targets")
