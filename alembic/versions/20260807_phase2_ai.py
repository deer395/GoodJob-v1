"""phase 2 opt-in AI settings and analyses

Revision ID: 20260807_phase2_ai
Revises: 20260806_phase2_import_calendar
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_phase2_ai"
down_revision = "20260806_phase2_import_calendar"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ai_settings"):
        op.create_table("ai_settings", sa.Column("id", sa.Integer, primary_key=True), sa.Column("ai_enabled", sa.Boolean, nullable=False, server_default=sa.false()), sa.Column("extraction_consent_version", sa.String), sa.Column("extraction_consented_at", sa.String), sa.Column("semantic_consent_version", sa.String), sa.Column("semantic_consented_at", sa.String))
    if not inspector.has_table("job_ai_analyses"):
        op.create_table("job_ai_analyses", sa.Column("id", sa.Integer, primary_key=True), sa.Column("job_id", sa.Integer, nullable=False), sa.Column("ai_score", sa.Integer, nullable=False), sa.Column("reasons", sa.Text, nullable=False), sa.Column("risks", sa.Text, nullable=False), sa.Column("model_name", sa.String, nullable=False), sa.Column("created_at", sa.String, nullable=False), sa.Column("prompt_version", sa.String, nullable=False), sa.Column("input_fingerprint", sa.String, nullable=False), sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"]))
        op.create_index("ix_job_ai_analyses_cache", "job_ai_analyses", ["job_id", "input_fingerprint", "prompt_version"])

def downgrade():
    op.drop_index("ix_job_ai_analyses_cache", table_name="job_ai_analyses")
    op.drop_table("job_ai_analyses")
    op.drop_table("ai_settings")
