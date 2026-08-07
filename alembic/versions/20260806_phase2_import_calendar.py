"""Add Phase 2 import provenance and calendar scheduling fields."""

from alembic import op
import sqlalchemy as sa


revision = "20260806_phase2_import_calendar"
down_revision = "20260806_progress"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "import_batches" not in tables:
        op.create_table(
            "import_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("filename", sa.Text(), nullable=False),
            sa.Column("imported_at", sa.Text(), nullable=False),
            sa.Column("total_rows", sa.Integer(), nullable=False),
            sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("column_mapping", sa.Text(), nullable=False),
            sa.Column("default_year", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
    job_columns = {column["name"] for column in inspector.get_columns("job_postings")}
    if "source_import_id" not in job_columns:
        op.add_column("job_postings", sa.Column("source_import_id", sa.Integer(), nullable=True))
    event_columns = {column["name"] for column in inspector.get_columns("application_events")}
    if "scheduled_at" not in event_columns:
        op.add_column("application_events", sa.Column("scheduled_at", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("application_events") as batch:
        batch.drop_column("scheduled_at")
    with op.batch_alter_table("job_postings") as batch:
        batch.drop_column("source_import_id")
    op.drop_table("import_batches")
