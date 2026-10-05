import sqlalchemy as sa
from alembic import op

revision = "0008_agent_dispatch"
down_revision = "0007_job_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs", sa.Column("require_plan_approval", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("jobs", sa.Column("planning_agent", sa.String(), nullable=False, server_default="claude"))
    for name in ("planning_model", "implementation_model", "audit_model", "paused_stage"):
        op.add_column("jobs", sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "require_plan_approval")
    for name in ("paused_stage", "audit_model", "implementation_model", "planning_model", "planning_agent"):
        op.drop_column("jobs", name)
