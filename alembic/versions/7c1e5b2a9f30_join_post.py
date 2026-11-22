"""Join post: remember the group message with the join button and live list

Revision ID: 7c1e5b2a9f30
Revises: 2a7f3c9d1e04
Create Date: 2026-11-22 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c1e5b2a9f30"
down_revision: str | Sequence[str] | None = "2a7f3c9d1e04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("join_message_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("join_message_digest", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.drop_column("join_message_digest")
        batch.drop_column("join_message_id")
