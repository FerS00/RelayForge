import sqlalchemy as sa
from alembic import op

revision = "0003_repositories"
down_revision = "0002_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("default_branch", sa.Text(), nullable=False),
        sa.Column("check_commands_json", sa.Text(), nullable=False),
        sa.Column("policy_profile", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
    )
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("repository_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("codex_thread_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("diff_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("diff_paths_json", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_jobs_repository_id_repositories",
            "repositories",
            ["repository_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_jobs_repository_id", "jobs", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_repository_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("fk_jobs_repository_id_repositories", type_="foreignkey")
        batch.drop_column("diff_paths_json")
        batch.drop_column("diff_text")
        batch.drop_column("codex_thread_id")
        batch.drop_column("repository_id")
    op.drop_table("repositories")
