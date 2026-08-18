"""add enrichment worker state

Revision ID: c41f32b8e7a1
Revises: 9b206caa3fb0
Create Date: 2026-08-17 19:25:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41f32b8e7a1"
down_revision: str | None = "9b206caa3fb0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("enrichment_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("locked_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    raise RuntimeError("Fridge migrations are forward-only")
