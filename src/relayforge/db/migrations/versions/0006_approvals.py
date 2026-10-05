import sqlalchemy as sa
from alembic import op

revision = "0006_approvals"
down_revision = "0005_findings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_json", sa.Text(), nullable=False),
        sa.Column("operation_hash", sa.String(length=64), nullable=False),
        sa.Column("diff_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("decision_idempotency_key", sa.String(), nullable=True),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("decided_at", sa.String(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_approvals_idempotency"),
        sa.UniqueConstraint("decision_idempotency_key", name="uq_approvals_decision_idempotency"),
    )
    op.create_index("ix_approvals_job_id", "approvals", ["job_id"])
    op.create_index("ix_approvals_operation_hash", "approvals", ["operation_hash"])
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_table(
        "approval_grants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "approval_id", sa.String(), sa.ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("matcher_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_approval_grants_approval_id", "approval_grants", ["approval_id"])
    op.create_index("ix_approval_grants_job_id", "approval_grants", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_approval_grants_job_id", table_name="approval_grants")
    op.drop_index("ix_approval_grants_approval_id", table_name="approval_grants")
    op.drop_table("approval_grants")
    op.drop_index("ix_approvals_status", table_name="approvals")
    op.drop_index("ix_approvals_operation_hash", table_name="approvals")
    op.drop_index("ix_approvals_job_id", table_name="approvals")
    op.drop_table("approvals")
