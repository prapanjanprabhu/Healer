import uuid

from tests.factories import DEFAULT_TEST_PASSWORD, make_user

PASSWORD = DEFAULT_TEST_PASSWORD


def login_as(client, db_session, *, role: str, email: str | None = None):
    """Creates a user with the given role and logs `client` in as them —
    cookies persist on `client` for subsequent requests in the same test.
    """
    email = email or f"{role.lower()}-{uuid.uuid4().hex[:6]}@healer.test"
    user = make_user(db_session, email=email, role_names=(role,))
    response = client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200
    return user
