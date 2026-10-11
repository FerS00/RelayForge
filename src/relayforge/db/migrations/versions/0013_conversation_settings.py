import sqlalchemy as sa
from alembic import op

revision = "0013_conversation_settings"
down_revision = "0012_previews"
branch_labels = None
depends_on = None

DEFAULT_TOOLS_JSON = (
    '{"commands":true,"git_local":true,"preview":true,"remote_delivery":false,'
    '"web_search":false,"write_files":true}'
)


def upgrade() -> None:
    op.add_column("conversations", sa.Column("effort", sa.String(), nullable=False, server_default=""))
    op.add_column(
        "conversations",
        sa.Column("tools_json", sa.Text(), nullable=False, server_default=DEFAULT_TOOLS_JSON),
    )
    op.add_column(
        "conversations", sa.Column("settings_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("chat_turns", sa.Column("effort", sa.String(), nullable=False, server_default=""))
    op.add_column("chat_turns", sa.Column("tools_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    # Plain ALTER TABLE DROP COLUMN avoids a batch rebuild that would cascade
    # deletes from conversations to their dependents.
    op.drop_column("chat_turns", "tools_json")
    op.drop_column("chat_turns", "effort")
    op.drop_column("conversations", "settings_version")
    op.drop_column("conversations", "tools_json")
    op.drop_column("conversations", "effort")
