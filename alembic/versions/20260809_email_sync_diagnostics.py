"""Persist only the latest aggregate, non-sensitive email-sync diagnostic."""

from alembic import op
import sqlalchemy as sa


revision = "20260809_email_sync_diagnostics"
down_revision = "20260809_data_safety"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_sync_diagnostics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("diagnostic_category", sa.Text(), nullable=False),
        sa.Column("scan_mailbox", sa.Text(), nullable=False),
        sa.Column("scan_days", sa.Integer(), nullable=False),
        sa.Column("scan_limit", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=True),
        sa.Column("deduplicated_count", sa.Integer(), nullable=True),
        sa.Column("parser_enabled", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("email_sync_diagnostics")
