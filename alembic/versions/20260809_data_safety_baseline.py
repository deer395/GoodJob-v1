"""Reconcile local schema under Alembic and protect email-event idempotency.

Revision ID: 20260809_data_safety
Revises: 20260807_email_parse_reason
"""
from alembic import op
import sqlalchemy as sa


revision = "20260809_data_safety"
down_revision = "20260807_email_parse_reason"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    event_columns = {column["name"] for column in inspector.get_columns("application_events")}
    if "action_deadline_at" not in event_columns:
        op.add_column("application_events", sa.Column("action_deadline_at", sa.Text(), nullable=True))
    email_columns = {column["name"] for column in inspector.get_columns("email_events")}
    if "extracted_city" not in email_columns:
        op.add_column("email_events", sa.Column("extracted_city", sa.Text(), nullable=True))
    if "proposed_action_deadline_at" not in email_columns:
        op.add_column("email_events", sa.Column("proposed_action_deadline_at", sa.Text(), nullable=True))
    if not inspector.has_table("email_event_links"):
        op.create_table(
            "email_event_links",
            sa.Column("email_event_id", sa.Integer(), sa.ForeignKey("email_events.id"), primary_key=True),
            sa.Column("application_event_id", sa.Integer(), sa.ForeignKey("application_events.id"), nullable=False, unique=True),
            sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
        op.execute("""
            INSERT OR IGNORE INTO email_event_links(email_event_id, application_event_id, idempotency_key, created_at)
            SELECT id, linked_application_event_id, 'email-event:' || id, COALESCE(updated_at, created_at)
            FROM email_events WHERE linked_application_event_id IS NOT NULL
        """)


def downgrade():
    # Removing link evidence can make a later replay unsafe; use a backup restore instead.
    raise RuntimeError("20260809_data_safety is intentionally irreversible; restore the pre-upgrade backup instead")
