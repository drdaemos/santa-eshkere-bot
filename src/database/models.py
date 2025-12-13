"""SQLAlchemy database models for Santa Eshkere bot"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models"""
    pass


class Group(Base):
    """Telegram group where bot is activated"""
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    group_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime] = mapped_column(default=datetime.now)
    disbanded_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    users: Mapped[list["User"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    exclusions: Mapped[list["Exclusion"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_groups_telegram_chat_id", "telegram_chat_id"),
        Index("idx_groups_is_active", "is_active"),
    )


class User(Base):
    """User who joined a Secret Santa group"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_username: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    real_name: Mapped[str] = mapped_column(Text, nullable=False)
    wishlist: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    joined_at: Mapped[datetime] = mapped_column(default=datetime.now)

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="users")
    given_assignments: Mapped[list["Assignment"]] = relationship(
        foreign_keys="Assignment.giver_id",
        back_populates="giver",
        cascade="all, delete-orphan"
    )
    received_assignments: Mapped[list["Assignment"]] = relationship(
        foreign_keys="Assignment.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("telegram_id", "group_id", name="uq_user_group"),
        Index("idx_users_telegram_id", "telegram_id"),
        Index("idx_users_group_id", "group_id"),
    )


class Exclusion(Base):
    """Exclusion rule: two users who shouldn't be matched"""
    __tablename__ = "exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user1_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user2_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="exclusions")
    user1: Mapped["User"] = relationship(foreign_keys=[user1_id])
    user2: Mapped["User"] = relationship(foreign_keys=[user2_id])

    __table_args__ = (
        UniqueConstraint("user1_id", "user2_id", "group_id", name="uq_exclusion"),
        CheckConstraint("user1_id < user2_id", name="ck_canonical_order"),
        Index("idx_exclusions_group_id", "group_id"),
    )


class Assignment(Base):
    """Secret Santa assignment: giver -> receiver"""
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    event_year: Mapped[int] = mapped_column(Integer, nullable=False)
    giver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    receiver_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    assigned_at: Mapped[datetime] = mapped_column(default=datetime.now)

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="assignments")
    giver: Mapped["User"] = relationship(foreign_keys=[giver_id], back_populates="given_assignments")
    receiver: Mapped["User"] = relationship(foreign_keys=[receiver_id], back_populates="received_assignments")

    __table_args__ = (
        UniqueConstraint("group_id", "event_year", "giver_id", name="uq_assignment"),
        Index("idx_assignments_group_id", "group_id"),
        Index("idx_assignments_event_year", "event_year"),
    )
