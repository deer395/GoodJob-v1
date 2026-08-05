"""Add optional JD original text without changing existing data."""
from alembic import op
import sqlalchemy as sa

revision = "20260805_description"
down_revision = "20260805_loop2"
branch_labels = None
depends_on = None

def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_postings")}
    if "description_text" not in columns:
        op.add_column("job_postings", sa.Column("description_text", sa.Text(), nullable=True))

def downgrade():
    with op.batch_alter_table("job_postings") as batch:
        batch.drop_column("description_text")
