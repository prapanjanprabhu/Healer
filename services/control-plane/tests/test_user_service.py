import pytest

from app.services import auth_service, user_service
from app.services.user_service import UserServiceError
from tests.factories import make_user


def test_create_user_hashes_the_password_and_assigns_roles(db_session):
    user = user_service.create_user(
        db_session,
        email="New.User@Healer.test",
        password="a-strong-password",
        role_names=["Operator"],
    )

    assert user.email == "new.user@healer.test"  # normalized
    assert user.password_hash != "a-strong-password"
    assert auth_service.get_role_names(user) == ["Operator"]


def test_create_user_rejects_a_duplicate_email(db_session):
    make_user(db_session, email="dup@healer.test")
    with pytest.raises(UserServiceError, match="already exists"):
        user_service.create_user(
            db_session, email="dup@healer.test", password="a-strong-password", role_names=["Viewer"]
        )


def test_create_user_rejects_an_unknown_role(db_session):
    with pytest.raises(UserServiceError, match="unknown role"):
        user_service.create_user(
            db_session,
            email="x@healer.test",
            password="a-strong-password",
            role_names=["SuperAdmin"],
        )


def test_create_user_rejects_an_empty_role_list(db_session):
    with pytest.raises(UserServiceError, match="at least one role"):
        user_service.create_user(
            db_session, email="x@healer.test", password="a-strong-password", role_names=[]
        )


def test_set_user_roles_replaces_the_existing_set(db_session):
    user = make_user(db_session, role_names=("Viewer",))
    user_service.set_user_roles(db_session, user, ["Administrator", "Operator"])

    assert auth_service.get_role_names(user) == ["Administrator", "Operator"]


def test_set_user_active_toggles_the_flag(db_session):
    user = make_user(db_session)
    user_service.set_user_active(db_session, user, False)
    assert user.is_active is False
    user_service.set_user_active(db_session, user, True)
    assert user.is_active is True


def test_list_role_names_returns_the_fixed_v1_roles():
    assert user_service.list_role_names() == ["Administrator", "Operator", "Viewer"]
