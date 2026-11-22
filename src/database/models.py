"""SQLAlchemy models.

A Group is a Telegram chat. Each group runs one Event (season) at a time:
open (people join) -> drawn (assignments sent) -> closed (archived when the
next season starts). Participants belong to an event, so every season starts
empty; exclusion rules belong to the group and are keyed by Telegram user id,
so "these two are a couple" carries over between seasons.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EventStatus:
    OPEN = "open"
    DRAWN = "drawn"
    CLOSED = "closed"


class Group(Base):
    """Telegram group where the bot was activated"""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    group_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    disbanded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    events: Mapped[list["Event"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    exclusions: Mapped[list["Exclusion"]] = relationship(back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_groups_is_active", "is_active"),)

    @property
    def title(self) -> str:
        return self.group_name or "Без названия"


class Event(Base):
    """One Secret Santa season in a group"""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=EventStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    drawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # the group message with the join button and live participant list
    join_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # digest of what that message shows now, so unchanged lists aren't re-sent
    join_message_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # joining closes at this moment (naive UTC); None = open until the season ends
    join_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # the admin who set it: told when it passes
    deadline_set_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # the passing of the deadline was handled (join post closed, admin told)
    deadline_handled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))

    group: Mapped[Group] = relationship(back_populates="events")
    participants: Mapped[list["Participant"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('open', 'drawn', 'closed')", name="ck_event_status"),
        Index("idx_events_group_id", "group_id"),
        # at most one current (not closed) season per group
        Index(
            "uq_events_current_per_group",
            "group_id",
            unique=True,
            sqlite_where=text("status != 'closed'"),
            postgresql_where=text("status != 'closed'"),
        ),
    )

    @property
    def year(self) -> int:
        return self.created_at.year


class Participant(Base):
    """A person taking part in one event"""

    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    real_name: Mapped[str] = mapped_column(Text, nullable=False)
    wishlist: Mapped[str] = mapped_column(Text, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    event: Mapped[Event] = relationship(back_populates="participants")

    __table_args__ = (
        UniqueConstraint("event_id", "telegram_id", name="uq_participant_event_user"),
        Index("idx_participants_telegram_id", "telegram_id"),
        Index("idx_participants_event_id", "event_id"),
    )


class Exclusion(Base):
    """Two people (by Telegram id) who must not be paired, in a group, across seasons"""

    __tablename__ = "exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    telegram_id_a: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_id_b: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    group: Mapped[Group] = relationship(back_populates="exclusions")

    __table_args__ = (
        UniqueConstraint("group_id", "telegram_id_a", "telegram_id_b", name="uq_exclusion_pair"),
        CheckConstraint("telegram_id_a < telegram_id_b", name="ck_exclusion_canonical_order"),
        Index("idx_exclusions_group_id", "group_id"),
    )


class Assignment(Base):
    """giver -> receiver within one event"""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    giver_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    receiver_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="CASCADE"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    event: Mapped[Event] = relationship(back_populates="assignments")
    giver: Mapped[Participant] = relationship(foreign_keys=[giver_id])
    receiver: Mapped[Participant] = relationship(foreign_keys=[receiver_id])

    __table_args__ = (
        UniqueConstraint("event_id", "giver_id", name="uq_assignment_giver"),
        UniqueConstraint("event_id", "receiver_id", name="uq_assignment_receiver"),
        CheckConstraint("giver_id != receiver_id", name="ck_assignment_not_self"),
        Index("idx_assignments_event_id", "event_id"),
        # ids are never reused (Postgres sequences don't; SQLite needs this):
        # message buttons name an assignment, and a repaired pairing must not
        # inherit the old one's buttons
        {"sqlite_autoincrement": True},
    )


class DmState(Base):
    """Per-user conversation state, kept in the DB so it survives redeploys"""

    __tablename__ = "dm_states"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    selected_group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    flow: Mapped[str | None] = mapped_column(String(32), nullable=True)
    flow_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
