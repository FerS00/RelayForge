import sqlalchemy as sa
from alembic import op

revision = "0005_findings"
down_revision = "0004_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "audit_step_id", sa.String(), sa.ForeignKey("job_steps.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("audit_no", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("file", sa.Text(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("triage_decision", sa.String(), nullable=True),
        sa.Column("triage_reason", sa.Text(), nullable=True),
        sa.Column("fixed_in_iteration", sa.Integer(), nullable=True),
    )
    op.create_index("ix_findings_job_id", "findings", ["job_id"])
    op.create_index("ix_findings_audit_step_id", "findings", ["audit_step_id"])
    op.create_index("uq_findings_audit_external", "findings", ["audit_step_id", "external_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_findings_audit_external", table_name="findings")
    op.drop_index("ix_findings_audit_step_id", table_name="findings")
    op.drop_index("ix_findings_job_id", table_name="findings")
    op.drop_table("findings")
