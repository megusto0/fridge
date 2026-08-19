"""product serving unit

Revision ID: a1f4c7d92b03
Revises: d72a5eb480fa
Create Date: 2026-08-19 01:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1f4c7d92b03"
down_revision: str | None = "d72a5eb480fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable with no default: every existing product starts as an
    # unanswered question. Defaulting them all to pieces or to grams would
    # be a guess wearing the clothes of an answer, and nobody would ever be
    # asked to correct it.
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(sa.Column("serving_unit", sa.String(length=8), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Fridge migrations are forward-only")
