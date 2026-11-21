import pytest

from app.core.config import Settings, _validate_non_local_settings


def _base_settings(**overrides) -> Settings:
    defaults = dict(
        environment="production",
        jwt_secret="a-real-random-secret",
        credential_encryption_key="a-real-random-key",
        dev_quick_login_enabled=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_local_dev_environment_allows_placeholders():
    settings = _base_settings(
        environment="development",
        jwt_secret="dev-secret-change-me",
        credential_encryption_key="dev-credential-key-change-me",
        dev_quick_login_enabled=True,
    )
    _validate_non_local_settings(settings)  # must not raise


def test_non_local_environment_rejects_placeholder_jwt_secret():
    settings = _base_settings(jwt_secret="dev-secret-change-me")
    with pytest.raises(RuntimeError, match="SF_JWT_SECRET"):
        _validate_non_local_settings(settings)


def test_non_local_environment_rejects_placeholder_credential_key():
    settings = _base_settings(credential_encryption_key="dev-credential-key-change-me")
    with pytest.raises(RuntimeError, match="SF_CREDENTIAL_ENCRYPTION_KEY"):
        _validate_non_local_settings(settings)


def test_non_local_environment_rejects_dev_quick_login():
    settings = _base_settings(dev_quick_login_enabled=True)
    with pytest.raises(RuntimeError, match="SF_DEV_QUICK_LOGIN_ENABLED"):
        _validate_non_local_settings(settings)


def test_non_local_environment_with_real_secrets_is_fine():
    settings = _base_settings()
    _validate_non_local_settings(settings)  # must not raise
