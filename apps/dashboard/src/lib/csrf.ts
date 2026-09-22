const CSRF_COOKIE_NAME = "healer_csrf";

// The CSRF cookie is deliberately not HttpOnly (see the control plane's
// app/core/cookies.py) specifically so same-origin JS can read it here and
// echo it back as a header — that's what proves the request came from the
// dashboard and not a cross-site page that can trigger but not read it.
export function readCsrfToken(): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE_NAME}=([^;]*)`));
  const value = match?.[1];
  return value ? decodeURIComponent(value) : null;
}
