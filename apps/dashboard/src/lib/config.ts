// Public base URL of the Control Plane API, as seen by the browser. Used by
// client components (login form, logout button). The dashboard talks only
// to the Control Plane — never directly to the database, agents, or the
// Gateway Manager (see docs/security-boundaries.md).
export const CONTROL_PLANE_URL =
  process.env.NEXT_PUBLIC_CONTROL_PLANE_URL ?? "http://localhost:8000";

// Server-side base URL, used by middleware.ts and server components. Inside
// Docker Compose, "localhost" from the dashboard container's own point of
// view is the dashboard container itself, not the control-plane one — so
// server-side code needs the Compose service hostname instead of the
// browser-facing localhost URL. Falls back to CONTROL_PLANE_URL for
// non-Docker local dev (`next dev` on the host talking to a host-run API).
export const CONTROL_PLANE_INTERNAL_URL =
  process.env.CONTROL_PLANE_INTERNAL_URL ?? CONTROL_PLANE_URL;
