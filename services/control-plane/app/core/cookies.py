"""Cookie names shared between the auth routes and the auth dependencies.

Design: access + refresh tokens are HttpOnly (never readable by JS, immune to
XSS token theft). The CSRF cookie is deliberately NOT HttpOnly — the
dashboard reads it and echoes it back as a header, so the double-submit
check can tell a same-origin fetch (which can read the cookie) apart from a
cross-site form/script (which can't). See docs/auth.md.
"""

ACCESS_COOKIE_NAME = "healer_access"
REFRESH_COOKIE_NAME = "healer_refresh"
CSRF_COOKIE_NAME = "healer_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
