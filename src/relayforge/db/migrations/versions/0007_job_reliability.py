import sqlalchemy as sa
from alembic import op

revision = "0007_job_reliability"
down_revision = "0006_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("retry_at", sa.String(), nullable=True))
    op.add_column("jobs", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "agent_health",
        sa.Column("agent", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("checked_at", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("rate_limited_until", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("agent_health")
    op.drop_column("jobs", "retry_count")
    op.drop_column("jobs", "retry_at")
