from app.db.models.notification import Notification
from tests.factories import make_user
from tests.support.auth import login_as
from tests.support.csrf import csrf_headers


def test_list_notifications_returns_broadcast_and_own(client, db_session):
    user = login_as(client, db_session, role="Administrator", email="admin-notif@healer.test")
    other_user = make_user(db_session, email="other-notif@healer.test")
    db_session.add(
        Notification(user_id=None, notification_type="self_healing_gave_up", message="broadcast")
    )
    db_session.add(
        Notification(user_id=user.id, notification_type="self_healing_gave_up", message="mine")
    )
    db_session.add(
        Notification(
            user_id=other_user.id,
            notification_type="self_healing_gave_up",
            message="someone else's",
        )
    )
    db_session.commit()

    response = client.get("/notifications")
    assert response.status_code == 200
    messages = {n["message"] for n in response.json()}
    # A subset check, not exact-set equality: this shared dev database also
    # carries real broadcast notifications from live-verification sessions
    # in earlier phases, which an Administrator's own listing legitimately
    # includes too. What matters here is that this test's own broadcast and
    # own-user notifications are visible, and another user's is not.
    assert {"broadcast", "mine"} <= messages
    assert "someone else's" not in messages


def test_mark_notification_read(client, db_session):
    user = login_as(client, db_session, role="Operator", email="operator-notif@healer.test")
    notification = Notification(
        user_id=user.id, notification_type="self_healing_gave_up", message="mine"
    )
    db_session.add(notification)
    db_session.commit()

    response = client.post(f"/notifications/{notification.id}/read", headers=csrf_headers(client))
    assert response.status_code == 204
    assert notification.read_at is not None


def test_cannot_mark_someone_elses_notification_read(client, db_session):
    login_as(client, db_session, role="Operator", email="operator-notif-2@healer.test")
    other_user = make_user(db_session, email="other-notif-2@healer.test")
    notification = Notification(
        user_id=other_user.id,
        notification_type="self_healing_gave_up",
        message="not yours",
    )
    db_session.add(notification)
    db_session.commit()

    response = client.post(f"/notifications/{notification.id}/read", headers=csrf_headers(client))
    assert response.status_code == 404
