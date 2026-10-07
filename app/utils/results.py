"""Result value objects shared by the checkers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.utils.enums import CheckStatus, CollectibleStatus, UsernameType


@dataclass
class CheckResult:
    """Outcome of a single username check."""

    username: str
    status: CheckStatus
    source: str
    reason: str | None = None
    detail: str | None = None
    entity_type: str | None = None
    title: str | None = None
    cached: bool = False
    duration_ms: int = 0
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_available(self) -> bool:
        return self.status is CheckStatus.AVAILABLE

    @property
    def is_definitive(self) -> bool:
        return self.status in (
            CheckStatus.AVAILABLE,
            CheckStatus.OCCUPIED,
            CheckStatus.INVALID,
        )

    @property
    def display(self) -> str:
        return f"@{self.username}"

    def to_cache(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "status": self.status.value,
            "source": self.source,
            "reason": self.reason,
            "detail": self.detail,
            "entity_type": self.entity_type,
            "title": self.title,
            "checked_at": self.checked_at.isoformat(),
        }

    @classmethod
    def from_cache(cls, payload: dict[str, Any]) -> "CheckResult":
        checked_at = payload.get("checked_at")
        try:
            parsed = datetime.fromisoformat(checked_at) if checked_at else datetime.now(timezone.utc)
        except ValueError:
            parsed = datetime.now(timezone.utc)
        return cls(
            username=payload.get("username", ""),
            status=CheckStatus(payload.get("status", CheckStatus.UNKNOWN.value)),
            source=payload.get("source", "cache"),
            reason=payload.get("reason"),
            detail=payload.get("detail"),
            entity_type=payload.get("entity_type"),
            title=payload.get("title"),
            cached=True,
            checked_at=parsed,
        )


@dataclass
class CollectibleResult:
    """Outcome of a collectible / Fragment lookup."""

    username: str
    status: CollectibleStatus = CollectibleStatus.UNKNOWN
    is_collectible: bool = False
    marketplace: str | None = None
    owner: str | None = None
    price: str | None = None
    purchase_date: str | None = None
    source: str = "collectible"
    reason: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def available(self) -> bool:
        return self.status is not CollectibleStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "status": self.status.value,
            "is_collectible": self.is_collectible,
            "marketplace": self.marketplace,
            "owner": self.owner,
            "price": self.price,
            "purchase_date": self.purchase_date,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass
class ScanItem:
    username: str
    status: CheckStatus
    username_type: UsernameType = UsernameType.BASIC


@dataclass
class ScanSummary:
    total: int = 0
    checked: int = 0
    available: int = 0
    occupied: int = 0
    collectible: int = 0
    invalid: int = 0
    unknown: int = 0
    errors: int = 0
    rate_limited: int = 0
    duration_seconds: float = 0.0
    available_usernames: list[str] = field(default_factory=list)
    collectible_usernames: list[str] = field(default_factory=list)
    flood_wait_seconds: float = 0.0
