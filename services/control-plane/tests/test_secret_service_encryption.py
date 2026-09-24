from app.db.models.secret import SecretRecord
from app.services import secret_service
from tests.factories import make_application


def test_set_secret_stores_ciphertext_not_plaintext(db_session):
    application = make_application(db_session)
    secret_service.set_secret(db_session, application.id, "API_KEY", "sk-live-abcdef123456")

    record = (
        db_session.query(SecretRecord).filter(SecretRecord.application_id == application.id).one()
    )
    assert record.encrypted_value != "sk-live-abcdef123456"
    assert "sk-live-abcdef123456" not in record.encrypted_value


def test_get_secret_values_returns_the_real_decrypted_value(db_session):
    application = make_application(db_session)
    secret_service.set_secret(db_session, application.id, "API_KEY", "sk-live-abcdef123456")

    values = secret_service.get_secret_values(db_session, application.id)
    assert values == ["sk-live-abcdef123456"]


def test_get_secret_dict_maps_key_to_decrypted_value(db_session):
    application = make_application(db_session)
    secret_service.set_secret(db_session, application.id, "DB_PASSWORD", "s3cr3t")

    values = secret_service.get_secret_dict(db_session, application.id)
    assert values == {"DB_PASSWORD": "s3cr3t"}


def test_updating_an_existing_secret_re_encrypts_it(db_session):
    application = make_application(db_session)
    secret_service.set_secret(db_session, application.id, "API_KEY", "old-value")
    secret_service.set_secret(db_session, application.id, "API_KEY", "new-value")

    assert secret_service.get_secret_values(db_session, application.id) == ["new-value"]


def test_list_secret_keys_never_exposes_the_value(db_session):
    application = make_application(db_session)
    secret_service.set_secret(db_session, application.id, "API_KEY", "sk-live-abcdef123456")

    keys = secret_service.list_secret_keys(db_session, application.id)
    assert len(keys) == 1
    assert keys[0].key == "API_KEY"
    # SecretRecord itself only ever carries ciphertext — there is no
    # plaintext attribute to accidentally serialize into a response.
    assert keys[0].encrypted_value != "sk-live-abcdef123456"
