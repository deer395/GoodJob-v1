from alembic import op
import sqlalchemy as sa

revision = "20260806_apps"
down_revision = "20260805_description"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("applications", sa.Column("id", sa.Integer, primary_key=True), sa.Column("job_id", sa.Integer, sa.ForeignKey("job_postings.id"), nullable=False, unique=True), sa.Column("status", sa.Text, nullable=False), sa.Column("applied_at", sa.Text), sa.Column("resume_version", sa.Text), sa.Column("next_action", sa.Text), sa.Column("notes", sa.Text), sa.Column("created_at", sa.Text, nullable=False), sa.Column("updated_at", sa.Text, nullable=False))
    op.create_table("checklist_items", sa.Column("id", sa.Integer, primary_key=True), sa.Column("application_id", sa.Integer, sa.ForeignKey("applications.id"), nullable=False), sa.Column("label", sa.Text, nullable=False), sa.Column("is_completed", sa.Boolean, nullable=False, server_default=sa.false()), sa.Column("is_predefined", sa.Boolean, nullable=False), sa.Column("sort_order", sa.Integer, nullable=False), sa.Column("created_at", sa.Text, nullable=False), sa.Column("updated_at", sa.Text, nullable=False))

def downgrade():
    op.drop_table("checklist_items"); op.drop_table("applications")
