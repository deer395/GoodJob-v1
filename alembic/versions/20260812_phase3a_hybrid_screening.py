"""Cache structured semantic screening signals for hybrid job matching.

The table is additive: existing job postings and legacy match_score values are
preserved while Python recomputes the displayed screening relevance.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260812_phase3a_hybrid_screening"
down_revision = "20260811_phase3a_matching"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_semantic_screenings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("input_fingerprint", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"]),
    )
    op.create_index("ix_job_semantic_screenings_cache", "job_semantic_screenings", ["job_id", "input_fingerprint", "prompt_version"])


def downgrade():
    op.drop_index("ix_job_semantic_screenings_cache", table_name="job_semantic_screenings")
    op.drop_table("job_semantic_screenings")
