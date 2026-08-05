"""Add radar profile and rule-matching fields."""
from alembic import op
import sqlalchemy as sa

revision = "20260805_loop2"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("candidate_profiles"):
        op.create_table("candidate_profiles", sa.Column("id", sa.Integer, primary_key=True), sa.Column("graduation_year", sa.Text), sa.Column("degree", sa.Text), sa.Column("school", sa.Text), sa.Column("major", sa.Text), sa.Column("target_cities", sa.Text), sa.Column("target_directions", sa.Text), sa.Column("target_industries", sa.Text), sa.Column("skills", sa.Text), sa.Column("constraints", sa.Text), sa.Column("created_at", sa.Text, nullable=False), sa.Column("updated_at", sa.Text, nullable=False))
    present = {column["name"] for column in inspector.get_columns("job_postings")}
    columns = [("department", sa.Text()), ("is_favorite", sa.Boolean(),), ("duplicate_confirmed", sa.Boolean()), ("match_score", sa.Integer()), ("match_reasons", sa.Text())]
    with op.batch_alter_table("job_postings") as batch:
        for name, column_type in columns:
            if name not in present:
                batch.add_column(sa.Column(name, column_type, nullable=False, server_default=sa.false()) if name in {"is_favorite", "duplicate_confirmed"} else sa.Column(name, column_type))

def downgrade():
    with op.batch_alter_table("job_postings") as batch:
        batch.drop_column("match_reasons"); batch.drop_column("match_score"); batch.drop_column("duplicate_confirmed"); batch.drop_column("is_favorite"); batch.drop_column("department")
    op.drop_table("candidate_profiles")
