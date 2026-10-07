"""Shared enums and value objects used across the scanner stack."""

from __future__ import annotations

from enum import Enum


class CheckStatus(str, Enum):
    """Result of a username availability check.

    ``UNKNOWN`` is deliberately distinct from ``AVAILABLE``: if Telegram did
    not give a trustworthy answer we must never claim the name is free.
    """

    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"
    RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"


class UsernameType(str, Enum):
    BASIC = "BASIC"
    COLLECTIBLE = "COLLECTIBLE"
    UNKNOWN = "UNKNOWN"


class CollectibleStatus(str, Enum):
    """Fragment-side lifecycle of a collectible username."""

    AVAILABLE_FOR_PURCHASE = "AVAILABLE_FOR_PURCHASE"
    OWNED = "OWNED"
    LISTED = "LISTED"
    NOT_DETECTED = "NOT_DETECTED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class MembershipStatus(str, Enum):
    """Telegram chat membership, normalised to a small set."""

    CREATOR = "creator"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"
    RESTRICTED = "restricted"
    LEFT = "left"
    KICKED = "kicked"
    UNKNOWN = "unknown"

    @property
    def grants_access(self) -> bool:
        return self in (
            MembershipStatus.CREATOR,
            MembershipStatus.ADMINISTRATOR,
            MembershipStatus.MEMBER,
            # A restricted member is still *in* the chat, so it counts.
            MembershipStatus.RESTRICTED,
        )


class Privilege(str, Enum):
    FREE = "FREE"
    VIP = "VIP"
    PREMIUM = "PREMIUM"
    ADMIN = "ADMIN"


class AdminRole(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    ADMIN = "ADMIN"
    MODERATOR = "MODERATOR"


class Permission(str, Enum):
    """Permission-based architecture: never branch on a privilege *name*."""

    USE_SCANNER = "use_scanner"
    CAN_MASS_SCAN = "can_mass_scan"
    PRIORITY_QUEUE = "priority_queue"
    NO_CAPTCHA = "no_captcha"
    MAX_SCAN_RESULTS_500 = "max_scan_results_500"
    MAX_SCAN_RESULTS_5000 = "max_scan_results_5000"
    ADMIN_USERS = "admin_users"
    ADMIN_BLACKLIST = "admin_blacklist"
    ADMIN_RESTRICTIONS = "admin_restrictions"
    ADMIN_PRIVILEGES = "admin_privileges"
    ADMIN_STATISTICS = "admin_statistics"
    ADMIN_LOGS = "admin_logs"
    ADMIN_SETTINGS = "admin_settings"
    ADMIN_SYSTEM = "admin_system"


PRIVILEGE_PERMISSIONS: dict[Privilege, frozenset[Permission]] = {
    Privilege.FREE: frozenset(
        {
            Permission.USE_SCANNER,
        }
    ),
    Privilege.VIP: frozenset(
        {
            Permission.USE_SCANNER,
            Permission.CAN_MASS_SCAN,
            Permission.PRIORITY_QUEUE,
            Permission.MAX_SCAN_RESULTS_500,
        }
    ),
    Privilege.PREMIUM: frozenset(
        {
            Permission.USE_SCANNER,
            Permission.CAN_MASS_SCAN,
            Permission.PRIORITY_QUEUE,
            Permission.NO_CAPTCHA,
            Permission.MAX_SCAN_RESULTS_500,
            Permission.MAX_SCAN_RESULTS_5000,
        }
    ),
    Privilege.ADMIN: frozenset(
        {
            Permission.USE_SCANNER,
            Permission.CAN_MASS_SCAN,
            Permission.PRIORITY_QUEUE,
            # Deliberately NOT NO_CAPTCHA: administrators go through the same
            # onboarding gate as everyone else (captcha, channel, chat).
            Permission.MAX_SCAN_RESULTS_500,
            Permission.MAX_SCAN_RESULTS_5000,
            Permission.ADMIN_USERS,
            Permission.ADMIN_BLACKLIST,
            Permission.ADMIN_RESTRICTIONS,
            Permission.ADMIN_PRIVILEGES,
            Permission.ADMIN_STATISTICS,
            Permission.ADMIN_LOGS,
            Permission.ADMIN_SETTINGS,
            Permission.ADMIN_SYSTEM,
        }
    ),
}

# A moderator is an operator without superuser powers.
MODERATOR_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.USE_SCANNER,
        Permission.CAN_MASS_SCAN,
        Permission.ADMIN_BLACKLIST,
        Permission.ADMIN_RESTRICTIONS,
    }
)


ADMIN_ROLE_PERMISSIONS: dict[AdminRole, frozenset[Permission]] = {
    AdminRole.SUPERADMIN: PRIVILEGE_PERMISSIONS[Privilege.ADMIN],
    AdminRole.ADMIN: frozenset(
        {
            Permission.USE_SCANNER,
            Permission.CAN_MASS_SCAN,
            Permission.PRIORITY_QUEUE,
            Permission.MAX_SCAN_RESULTS_5000,
            Permission.ADMIN_USERS,
            Permission.ADMIN_RESTRICTIONS,
            Permission.ADMIN_PRIVILEGES,
            Permission.ADMIN_STATISTICS,
            Permission.ADMIN_SYSTEM,
        }
    ),
    AdminRole.MODERATOR: MODERATOR_PERMISSIONS,
}


def permissions_for(privilege: Privilege) -> frozenset[Permission]:
    return PRIVILEGE_PERMISSIONS.get(privilege, frozenset())


def admin_permissions_for(role: AdminRole) -> frozenset[Permission]:
    return ADMIN_ROLE_PERMISSIONS.get(role, frozenset())
