"""Seasons: events, per-event participants, group-level rules, DB-backed DM state

Converts the 2025 schema (users per group, assignments by EVENT_YEAR):
- each group with assignments -> one CLOSED event holding those users and
  the pairs of its latest year; a group with users but no draw -> an OPEN event
- exclusions are re-keyed from user row ids to Telegram ids (canonical order)

Revision ID: 2a7f3c9d1e04
Revises: 65a064dc1941
Create Date: 2026-11-21 20:00:00

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "2a7f3c9d1e04"
down_revision: str | Sequence[str] | None = "65a064dc1941"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dt(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value  # type: ignore[return-value]
    return datetime.fromisoformat(str(value))


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now()

    old_groups = bind.execute(sa.text("SELECT id, activated_at FROM groups")).fetchall()
    old_users = bind.execute(
        sa.text("SELECT id, telegram_id, telegram_username, real_name, wishlist, group_id, joined_at FROM users")
    ).fetchall()
    old_assignments = bind.execute(
        sa.text("SELECT group_id, event_year, giver_id, receiver_id, assigned_at FROM assignments")
    ).fetchall()
    old_exclusions = bind.execute(sa.text("SELECT user1_id, user2_id, group_id, created_at FROM exclusions")).fetchall()

    op.drop_table("assignments")
    op.drop_table("exclusions")
    op.drop_table("users")
    op.drop_index("idx_groups_telegram_chat_id", table_name="groups")

    events = op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("drawn_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'drawn', 'closed')", name="ck_event_status"),
    )
    op.create_index("idx_events_group_id", "events", ["group_id"])
    op.create_index(
        "uq_events_current_per_group",
        "events",
        ["group_id"],
        unique=True,
        sqlite_where=sa.text("status != 'closed'"),
        postgresql_where=sa.text("status != 'closed'"),
    )

    participants = op.create_table(
        "participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("real_name", sa.Text(), nullable=False),
        sa.Column("wishlist", sa.Text(), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", "telegram_id", name="uq_participant_event_user"),
    )
    op.create_index("idx_participants_telegram_id", "participants", ["telegram_id"])
    op.create_index("idx_participants_event_id", "participants", ["event_id"])

    exclusions = op.create_table(
        "exclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id_a", sa.BigInteger(), nullable=False),
        sa.Column("telegram_id_b", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("group_id", "telegram_id_a", "telegram_id_b", name="uq_exclusion_pair"),
        sa.CheckConstraint("telegram_id_a < telegram_id_b", name="ck_exclusion_canonical_order"),
    )
    op.create_index("idx_exclusions_group_id", "exclusions", ["group_id"])

    assignments = op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("giver_id", sa.Integer(), sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("receiver_id", sa.Integer(), sa.ForeignKey("participants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", "giver_id", name="uq_assignment_giver"),
        sa.UniqueConstraint("event_id", "receiver_id", name="uq_assignment_receiver"),
        sa.CheckConstraint("giver_id != receiver_id", name="ck_assignment_not_self"),
    )
    op.create_index("idx_assignments_event_id", "assignments", ["event_id"])

    op.create_table(
        "dm_states",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("selected_group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("flow", sa.String(32), nullable=True),
        sa.Column("flow_data", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # --- data ------------------------------------------------------------------
    users_by_group: dict[int, list] = {}
    for u in old_users:
        users_by_group.setdefault(u.group_id, []).append(u)
    pairs_by_group: dict[int, list] = {}
    for a in old_assignments:
        pairs_by_group.setdefault(a.group_id, []).append(a)
    user_by_id = {u.id: u for u in old_users}

    event_rows, participant_rows, assignment_rows = [], [], []
    next_event_id = 1
    for g in old_groups:
        members = users_by_group.get(g.id, [])
        pairs = pairs_by_group.get(g.id, [])
        if not members and not pairs:
            continue
        event_id = next_event_id
        next_event_id += 1
        joined = [_dt(u.joined_at) for u in members if u.joined_at is not None]
        created_at = min(joined) if joined else (_dt(g.activated_at) or now)
        if pairs:
            latest_year = max(a.event_year for a in pairs)
            pairs = [a for a in pairs if a.event_year == latest_year]
            drawn_at = max((_dt(a.assigned_at) for a in pairs if a.assigned_at is not None), default=now)
            event_rows.append({"id": event_id, "group_id": g.id, "status": "closed", "created_at": created_at, "drawn_at": drawn_at, "closed_at": now})
        else:
            event_rows.append({"id": event_id, "group_id": g.id, "status": "open", "created_at": created_at, "drawn_at": None, "closed_at": None})
        for u in members:
            participant_rows.append(
                {
                    "id": u.id,  # keep ids so old assignment rows map 1:1
                    "event_id": event_id,
                    "telegram_id": u.telegram_id,
                    "telegram_username": u.telegram_username,
                    "real_name": u.real_name,
                    "wishlist": u.wishlist or "",
                    "joined_at": _dt(u.joined_at) or now,
                }
            )
        member_ids = {u.id for u in members}
        for a in pairs:
            if a.giver_id in member_ids and a.receiver_id in member_ids and a.giver_id != a.receiver_id:
                assignment_rows.append(
                    {"event_id": event_id, "giver_id": a.giver_id, "receiver_id": a.receiver_id, "assigned_at": _dt(a.assigned_at) or now, "delivered_at": None}
                )

    exclusion_rows, seen = [], set()
    for e in old_exclusions:
        u1, u2 = user_by_id.get(e.user1_id), user_by_id.get(e.user2_id)
        if u1 is None or u2 is None or u1.telegram_id == u2.telegram_id:
            continue
        a, b = sorted((u1.telegram_id, u2.telegram_id))
        if (e.group_id, a, b) in seen:
            continue
        seen.add((e.group_id, a, b))
        exclusion_rows.append({"group_id": e.group_id, "telegram_id_a": a, "telegram_id_b": b, "created_at": _dt(e.created_at) or now})

    if event_rows:
        op.bulk_insert(events, event_rows)
    if participant_rows:
        op.bulk_insert(participants, participant_rows)
    if assignment_rows:
        op.bulk_insert(assignments, assignment_rows)
    if exclusion_rows:
        op.bulk_insert(exclusions, exclusion_rows)

    if bind.dialect.name == "postgresql":
        # explicit ids were inserted; move sequences past them
        for table in ("events", "participants"):
            op.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
            )


def downgrade() -> None:
    raise NotImplementedError("Seasons migration is one-way; restore the pre-migration backup instead.")
