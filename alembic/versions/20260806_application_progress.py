"""Add application events and next-action plan time for loop 4 progress."""

from alembic import op
import sqlalchemy as sa


revision = "20260806_progress"
down_revision = "20260806_apps"
branch_labels = None
depends_on = None


def upgrade():
    # `JobStore.initialize` can create a fresh local database before Alembic is
    # first run. Inspecting first makes this upgrade safe for that legacy path.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("applications")}
    if "next_action_due_at" not in columns:
        op.add_column("applications", sa.Column("next_action_due_at", sa.Text(), nullable=True))
    if "application_events" not in inspector.get_table_names():
        op.create_table(
            "application_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("event_date", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
    # Safe one-time backfill: only historical applications with a real applied_at
    # and no existing 投递 event receive the minimum evidence event.
    op.execute("""
        INSERT INTO application_events(application_id,event_type,event_date,description,created_at)
        SELECT a.id,'已投递',a.applied_at,'用户确认已在官方渠道提交申请',a.applied_at
        FROM applications a
        WHERE a.applied_at IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM application_events e
            WHERE e.application_id=a.id AND e.event_type='已投递'
          )
    """)


def downgrade():
    # Event history is intentionally removed only when the caller explicitly
    # downgrades the schema. A normal upgrade never fabricates later-stage data.
    op.drop_table("application_events")
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("next_action_due_at")
