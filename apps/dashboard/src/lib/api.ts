import { CONTROL_PLANE_URL } from "@/lib/config";
import { readCsrfToken } from "@/lib/csrf";

/** Client-side fetch to the Control Plane: sends cookies, and — for
 * mutating methods — the CSRF header the cookie-based session requires.
 * Server components should fetch the Control Plane directly instead (see
 * src/app/(dashboard)/layout.tsx) so they can use CONTROL_PLANE_INTERNAL_URL.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);

  if (method !== "GET" && method !== "HEAD") {
    const csrfToken = readCsrfToken();
    if (csrfToken) {
      headers.set("X-CSRF-Token", csrfToken);
    }
    if (init.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }

  return fetch(`${CONTROL_PLANE_URL}${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });
}
