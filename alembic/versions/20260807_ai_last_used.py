"""record last successful use of each opt-in AI capability.

Revision ID: 20260807_ai_last_used
Revises: 20260807_phase2_ai
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_ai_last_used"
down_revision = "20260807_phase2_ai"
branch_labels = None
depends_on = None

def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("ai_settings")}
    if "extraction_last_used_at" not in columns:
        op.add_column("ai_settings", sa.Column("extraction_last_used_at", sa.String()))
    if "semantic_last_used_at" not in columns:
        op.add_column("ai_settings", sa.Column("semantic_last_used_at", sa.String()))

def downgrade():
    op.drop_column("ai_settings", "semantic_last_used_at")
    op.drop_column("ai_settings", "extraction_last_used_at")
