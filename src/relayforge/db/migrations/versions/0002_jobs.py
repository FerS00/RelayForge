import sqlalchemy as sa
from alembic import op

revision = "0002_jobs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("workflow", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Text(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("approval_kind", sa.Text(), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("base_sha", sa.Text(), nullable=True),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("worktree_path", sa.Text(), nullable=True),
        sa.Column("orchestrator_session_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.UniqueConstraint("number"),
        sa.UniqueConstraint("conversation_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_updated_at", "jobs", ["updated_at"])
    op.create_index("ix_jobs_conversation_updated", "jobs", ["conversation_id", "updated_at"])

    op.create_table(
        "job_steps",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("pid_create_time", sa.Float(), nullable=True),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("resume_token", sa.Text(), nullable=True),
        sa.Column("resumable", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("raw_log_path", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
    )
    op.create_index("ix_job_steps_job_id", "job_steps", ["job_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.Text(), sa.ForeignKey("job_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("redacted", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])

    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("job_id", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_events_job_id_jobs", "jobs", ["job_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_events_job_id_seq", "events", ["job_id", "seq"])


def downgrade() -> None:
    op.execute("DELETE FROM events WHERE job_id IS NOT NULL")
    op.drop_index("ix_events_job_id_seq", table_name="events")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("fk_events_job_id_jobs", type_="foreignkey")
        batch_op.drop_column("job_id")
    op.drop_index("ix_artifacts_job_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_job_steps_job_id", table_name="job_steps")
    op.drop_table("job_steps")
    op.drop_index("ix_jobs_conversation_updated", table_name="jobs")
    op.drop_index("ix_jobs_updated_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
