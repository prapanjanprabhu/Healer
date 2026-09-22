from app.core.cookies import CSRF_COOKIE_NAME


def csrf_headers(client) -> dict:
    token = client.cookies.get(CSRF_COOKIE_NAME)
    assert token is not None, "expected a CSRF cookie to be set after login"
    return {"X-CSRF-Token": token}
