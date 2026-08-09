"""safe email parse failure reason

Revision ID: 20260807_email_parse_reason
Revises: 20260807_imap_email_events
"""
from alembic import op
import sqlalchemy as sa
revision='20260807_email_parse_reason'; down_revision='20260807_imap_email_events'; branch_labels=None; depends_on=None
def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("email_events")}
    if "parse_error" not in columns:
        op.add_column('email_events', sa.Column('parse_error', sa.String()))
def downgrade(): op.drop_column('email_events','parse_error')
