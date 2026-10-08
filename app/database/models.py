"""SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.enums import Privilege


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    captcha_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channel_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chat_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Generic per-subscription verification: {subscription_key: iso_timestamp}.
    # channel/chat are mirrored into the two columns above for compatibility.
    subscriptions_verified: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    banned_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    privilege: Mapped[str] = mapped_column(String(16), default=Privilege.FREE.value)
    admin_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    settings: Mapped["UserSetting | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    searches: Mapped[list["Search"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_users_username_lower", text("lower(username)")),)

    @property
    def is_admin(self) -> bool:
        return self.privilege == Privilege.ADMIN.value


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="searches")


class UsernameCheck(Base):
    __tablename__ = "username_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(32))
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (Index("ix_username_checks_lookup", "username", "type", "checked_at"),)


class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    default_mode: Mapped[str] = mapped_column(String(32), default="basic")
    results_limit: Mapped[int] = mapped_column(Integer, default=50)
    # Empty string means "not chosen yet" -> the language picker is shown before
    # anything else on /start. Using "" instead of NULL keeps the column NOT NULL,
    # so no schema migration is needed.
    language: Mapped[str] = mapped_column(String(8), default="")
    # --- search defaults, so the wizard opens pre-filled -------------------
    search_length: Mapped[int] = mapped_column(Integer, default=8)
    search_digits: Mapped[bool] = mapped_column(Boolean, default=False)
    search_min_score: Mapped[int] = mapped_column(Integer, default=40)
    # The wizard's mask, kept here (not only in the FSM) so navigating home -
    # which clears the FSM - does not silently drop it. "" means no mask.
    search_mask: Mapped[str] = mapped_column(String(64), default="")
    # --- daily drop: a search a day, delivered as a message ----------------
    daily_drop: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_drop_last: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="settings")


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class BotSetting(Base):
    """Runtime-tunable settings editable from the admin panel.

    Only safe, non-secret values live here. BOT_TOKEN / API_HASH stay in .env.
    """

    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UsernameCacheRow(Base):
    """Optional durable mirror of the Redis cache (survives Redis restarts)."""

    __tablename__ = "username_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("cache_key", name="uq_username_cache_key"),)


class Trap(Base):
    """A username the user wants to be told about the moment it frees up.

    Telegram has no "username released" event, so this is polled. The row keeps
    the polling state so a restart does not lose or duplicate notifications.
    """

    __tablename__ = "traps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # "name"  watches one exact username for release;
    # "mask"  is a sniper that generates candidates from a mask each sweep;
    # "collectible" watches one name on Fragment for a listing/price change;
    # "listing" watches a keyword and reports NEW Fragment listings that match.
    kind: Mapped[str] = mapped_column(String(16), default="name")
    username: Mapped[str] = mapped_column(String(64), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # For "listing" this holds the seen-name set ("ls:a,b,c"); for the others a
    # compact state token, so the column is sized for the longest case.
    last_status: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    freed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("telegram_id", "username", name="uq_trap_user_name"),
    )


class Battle(Base):
    """A username duel, either played locally or sent to a chat as a challenge."""

    __tablename__ = "battles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenger_id: Mapped[int] = mapped_column(BigInteger, index=True)
    challenger_username: Mapped[str] = mapped_column(String(64))
    rival_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rival_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    winner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PortfolioItem(Base):
    """A collectible username the user says they own, tracked for its value.

    The value is refreshed from Fragment on demand; the last reading is kept so
    the portfolio screen is instant and can show a change since the last check.
    """

    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_price: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("telegram_id", "username", name="uq_portfolio_user_name"),
    )


class Favorite(Base):
    """A username the user saved, with an optional note."""
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("telegram_id", "username", name="uq_favorite_user_name"),
    )


class FreeName(Base):
    """A username Telegram has confirmed as *claimable*, kept ready to hand out.

    Telegram rate-limits the authoritative availability check hard (roughly
    20-30 calls per account per minute), and hunting one name on demand costs
    several calls because most candidates are taken. That is why a search used
    to end in an apology instead of a name whenever the bot was busy.

    Verification is therefore decoupled from delivery: a background harvester
    spends the *idle* quota proving names free and parks them here, and a search
    serves one after a single re-confirmation. The re-confirmation is what keeps
    the promise honest - a stored name is only handed over when Telegram still
    answers "claimable" for it at that moment. A stale row (somebody claimed the
    name meanwhile) is dropped and the search carries on.
    """

    __tablename__ = "free_names"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Total length, and whether the name carries digits: both are user filters,
    # so a stored name can only be served to a search that asked for that shape.
    length: Mapped[int] = mapped_column(Integer, default=0, index=True)
    has_digits: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # The bot's own taste score, so the prettiest stored names are served first.
    score: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(24), default="harvest")
    # When Telegram last confirmed the name claimable. Old rows are pruned: a
    # free name can be claimed by anybody at any moment.
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set when a search picks the row up, so two concurrent searches can never be
    # handed the same name. The row returns to the pool if delivery does not
    # complete (see the reservation window in the repository).
    served_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
