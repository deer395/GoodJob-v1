"""store explicit locations for Phase 3B email proposals

Revision ID: 20260812_phase3b_email_location
Revises: 20260812_phase3b_email_understanding
"""
from alembic import op
import sqlalchemy as sa

revision = "20260812_phase3b_email_location"
down_revision = "20260812_phase3b_email_understanding"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("email_event_proposals")}
    if "location" not in columns:
        op.add_column("email_event_proposals", sa.Column("location", sa.Text(), nullable=False, server_default=""))


def downgrade():
    with op.batch_alter_table("email_event_proposals") as batch:
        batch.drop_column("location")
