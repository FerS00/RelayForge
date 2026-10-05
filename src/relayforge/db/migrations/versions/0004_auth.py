import sqlalchemy as sa
from alembic import op

revision = "0004_auth"
down_revision = "0003_repositories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("consumed_at", sa.String(), nullable=True),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("secret_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("tailscale_login", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.String(), nullable=True),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("pairing_codes")
