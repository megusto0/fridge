"""mockup backend contracts

Revision ID: d72a5eb480fa
Revises: c41f32b8e7a1
Create Date: 2026-08-17 22:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d72a5eb480fa"
down_revision: str | None = "c41f32b8e7a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("meal_prep_batches", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "name_source",
                sa.String(length=32),
                server_default="manual",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("cooked_yield_g", sa.Numeric(precision=14, scale=3), nullable=True)
        )
        batch_op.add_column(sa.Column("finalized_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True)))

    with op.batch_alter_table("meal_prep_containers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Fridge migrations are forward-only")
