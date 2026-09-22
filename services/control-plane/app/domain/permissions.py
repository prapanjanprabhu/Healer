"""V1 role -> permission matrix.

Administrator: full V1 access ("*").
Operator: deploy/scale/restart/stop/rollback/view — no user/security admin.
Viewer: read-only.
"""

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Administrator": {"*"},
    "Operator": {"view", "deploy", "scale", "restart", "stop", "rollback"},
    "Viewer": {"view"},
}


def has_permission(roles: set[str], permission: str) -> bool:
    for role in roles:
        granted = ROLE_PERMISSIONS.get(role, set())
        if "*" in granted or permission in granted:
            return True
    return False
