"""local IMAP email events

Revision ID: 20260807_imap_email_events
Revises: 20260807_ai_last_used
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_imap_email_events"
down_revision = "20260807_ai_last_used"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("ai_settings", sa.Column("enable_email_parsing", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("email_dedup", sa.Column("id", sa.Integer, primary_key=True), sa.Column("dedup_key", sa.String, nullable=False, unique=True), sa.Column("key_type", sa.String, nullable=False), sa.Column("mailbox", sa.String, nullable=False, server_default="INBOX"), sa.Column("uid", sa.String), sa.Column("uid_validity", sa.String), sa.Column("message_id", sa.String), sa.Column("content_hash", sa.String), sa.Column("action", sa.String, nullable=False), sa.Column("processed_at", sa.String, nullable=False))
    op.create_table("email_events", sa.Column("id", sa.Integer, primary_key=True), sa.Column("dedup_key", sa.String, nullable=False, unique=True), sa.Column("message_id", sa.String), sa.Column("sender_domain", sa.String), sa.Column("subject", sa.String, nullable=False), sa.Column("snippet", sa.String, nullable=False), sa.Column("received_at", sa.String, nullable=False), sa.Column("category", sa.String), sa.Column("summary", sa.String), sa.Column("confidence", sa.Float), sa.Column("extracted_company", sa.String), sa.Column("extracted_title", sa.String), sa.Column("proposed_application_id", sa.Integer), sa.Column("proposed_scheduled_at", sa.String), sa.Column("status", sa.String, nullable=False, server_default="pending"), sa.Column("linked_application_event_id", sa.Integer), sa.Column("parser_version", sa.String), sa.Column("created_at", sa.String, nullable=False), sa.Column("updated_at", sa.String, nullable=False))

def downgrade():
    op.drop_table("email_events"); op.drop_table("email_dedup"); op.drop_column("ai_settings", "enable_email_parsing")
