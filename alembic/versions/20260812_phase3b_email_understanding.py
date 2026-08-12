"""phase 3b explainable email proposals

Revision ID: 20260812_phase3b_email_understanding
Revises: 20260812_phase3a_hybrid_screening
"""
from alembic import op
import sqlalchemy as sa

revision = "20260812_phase3b_email_understanding"
down_revision = "20260812_phase3a_hybrid_screening"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "email_event_proposals" not in inspector.get_table_names():
        op.create_table(
            "email_event_proposals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email_event_id", sa.Integer(), sa.ForeignKey("email_events.id"), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("category", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("suggested_action", sa.Text(), nullable=False, server_default=""),
            sa.Column("confidence", sa.Integer(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("scheduled_at", sa.Text()),
            sa.Column("action_deadline_at", sa.Text()),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("linked_application_event_id", sa.Integer(), sa.ForeignKey("application_events.id"), unique=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )


def downgrade():
    op.drop_table("email_event_proposals")
