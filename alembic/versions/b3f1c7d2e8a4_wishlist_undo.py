"""Wishlist undo: keep what the last change replaced

Revision ID: b3f1c7d2e8a4
Revises: 9d4b8e1f6a27
Create Date: 2026-11-22 22:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3f1c7d2e8a4"
down_revision: str | Sequence[str] | None = "9d4b8e1f6a27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("participants") as batch:
        batch.add_column(sa.Column("previous_wishlist", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("participants") as batch:
        batch.drop_column("previous_wishlist")
