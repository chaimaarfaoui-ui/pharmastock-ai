"""Role -> permission mapping. Enforced server-side via require_permission()."""
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"users:manage", "settings:manage", "audit:read", "inventory:read", "inventory:write",
              "movements:write", "purchasing:write", "forecast:read", "analytics:read"},
    "manager": {"inventory:read", "inventory:write", "movements:write", "purchasing:write",
                "forecast:read", "analytics:read", "audit:read"},
    "employee": {"inventory:read", "movements:write"},
}
