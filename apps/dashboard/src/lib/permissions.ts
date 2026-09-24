// Mirrors services/control-plane/app/domain/permissions.py's role -> permission
// matrix, so the dashboard can hide destructive/administrative actions from
// users who don't hold them — a UX courtesy only. The Control Plane API is
// the actual enforcement point; every mutating request is re-checked there
// regardless of what this file decides to show or hide.
const ROLE_PERMISSIONS: Record<string, Set<string> | "*"> = {
  Administrator: "*",
  Operator: new Set(["view", "deploy", "scale", "restart", "stop", "rollback"]),
  Viewer: new Set(["view"]),
};

export function hasPermission(roles: string[], permission: string): boolean {
  for (const role of roles) {
    const granted = ROLE_PERMISSIONS[role];
    if (granted === "*") return true;
    if (granted?.has(permission)) return true;
  }
  return false;
}

export function isAdministrator(roles: string[]): boolean {
  return roles.includes("Administrator");
}
