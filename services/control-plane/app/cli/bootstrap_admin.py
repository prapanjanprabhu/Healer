"""Create the first Administrator account.

    python -m app.cli.bootstrap_admin --email admin@example.com --password 'a strong password'

Reads HEALER_BOOTSTRAP_ADMIN_EMAIL / HEALER_BOOTSTRAP_ADMIN_PASSWORD if the
flags are omitted. Idempotent: does nothing if a user with that email
already exists. Requires `alembic upgrade head` to have run first (the
Administrator role must already be seeded).
"""

import argparse
import os
import sys

from app.core.security import hash_password
from app.db.models.user import User, UserRole
from app.db.session import SessionLocal
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository


def bootstrap(email: str, password: str) -> None:
    email = email.strip().lower()
    session = SessionLocal()
    try:
        user_repo = UserRepository(session)
        if user_repo.get_by_email(email) is not None:
            print(f"user {email} already exists — nothing to do")
            return

        admin_role = RoleRepository(session).get_by_name("Administrator")
        if admin_role is None:
            sys.exit("Administrator role not found — run `alembic upgrade head` first")

        user = User(email=email, password_hash=hash_password(password), is_active=True)
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        session.commit()
        print(f"created initial Administrator: {email}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=os.environ.get("HEALER_BOOTSTRAP_ADMIN_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("HEALER_BOOTSTRAP_ADMIN_PASSWORD"))
    args = parser.parse_args()

    if not args.email or not args.password:
        parser.error(
            "--email/--password (or HEALER_BOOTSTRAP_ADMIN_EMAIL/"
            "HEALER_BOOTSTRAP_ADMIN_PASSWORD) are required"
        )

    bootstrap(args.email, args.password)


if __name__ == "__main__":
    main()
