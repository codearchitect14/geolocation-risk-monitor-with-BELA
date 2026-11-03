"""Role to permission map from the security specification (section 10)."""

from __future__ import annotations

ROLES = ("viewer", "analyst", "manager", "tenant_admin", "finance_analyst", "platform_admin")
TENANT_ROLES = ("viewer", "analyst", "manager", "tenant_admin")
MFA_REQUIRED_ROLES = ("tenant_admin", "platform_admin")

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"view"}),
    "analyst": frozenset({"view", "alerts.act"}),
    "manager": frozenset({"view", "alerts.act", "assets.write", "rules.manage"}),
    "tenant_admin": frozenset({"view", "alerts.act", "assets.write", "rules.manage", "admin.manage", "audit.view"}),
    "finance_analyst": frozenset({"revenue.view"}),
    "platform_admin": frozenset(
        {
            "view",
            "alerts.act",
            "assets.write",
            "rules.manage",
            "admin.manage",
            "audit.view",
            "revenue.view",
            "platform.manage",
        }
    ),
}

# What an API key scope grants. Keys never reach administration, billing, or platform functions.
SCOPE_PERMISSIONS: dict[str, frozenset[str]] = {
    "read": frozenset({"view"}),
    "alerts": frozenset({"alerts.act"}),
    "assets:write": frozenset({"assets.write"}),
    "reports": frozenset({"rules.manage"}),
}
VALID_SCOPES = tuple(SCOPE_PERMISSIONS)


def permissions_for_role(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for_scopes(scopes: list[str]) -> frozenset[str]:
    granted: set[str] = set()
    for scope in scopes:
        granted |= SCOPE_PERMISSIONS.get(scope, frozenset())
    return frozenset(granted)
