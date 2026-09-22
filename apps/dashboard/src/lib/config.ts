// Base URL of the Control Plane API. The dashboard talks only to the Control
// Plane — never directly to the database, agents, or the Gateway Manager
// (see docs/security-boundaries.md).
export const CONTROL_PLANE_URL =
  process.env.NEXT_PUBLIC_CONTROL_PLANE_URL ?? "http://localhost:8000";
