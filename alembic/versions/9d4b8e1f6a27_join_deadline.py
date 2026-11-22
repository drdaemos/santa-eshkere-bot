"""Joining deadline per season; assignment ids never reused on SQLite

Revision ID: 9d4b8e1f6a27
Revises: 7c1e5b2a9f30
Create Date: 2026-11-22 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d4b8e1f6a27"
down_revision: str | Sequence[str] | None = "7c1e5b2a9f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.add_column(sa.Column("join_deadline", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("deadline_set_by", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("deadline_handled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    # Anonymous-message buttons carry an assignment id. Postgres never reuses
    # ids; SQLite reuses the highest one unless the table uses AUTOINCREMENT.
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("assignments", recreate="always", table_kwargs={"sqlite_autoincrement": True}):
            pass


def downgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.drop_column("deadline_handled")
        batch.drop_column("deadline_set_by")
        batch.drop_column("join_deadline")
