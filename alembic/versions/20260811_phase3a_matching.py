"""Compatibility marker for the archived layered-matching experiment.

Some local databases reached this revision before the experiment was archived.
Its data structures are intentionally not part of the hybrid product schema,
but Alembic must recognise the historic revision so those databases can upgrade
without data loss.  Fresh hybrid databases pass through this schema-neutral
marker and then receive only the hybrid screening table.
"""

revision = "20260811_phase3a_matching"
down_revision = "20260809_email_sync_diagnostics"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
