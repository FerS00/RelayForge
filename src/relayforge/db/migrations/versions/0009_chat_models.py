import sqlalchemy as sa
from alembic import op

revision = "0009_chat_models"
down_revision = "0008_agent_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("model", sa.String(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("conversations", "model")
