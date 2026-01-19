from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.exceptions import IHSecretNotFound
from infrahouse_core.aws.secretsmanager import Secret


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def test_name():
    """Test name property returns the secret name."""
    secret = Secret("my-secret", region="us-east-1")
    assert secret.name == "my-secret"


def test_exists_true():
    """Test exists returns True when secret exists."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_secret.return_value = {"ARN": "arn:aws:secretsmanager:us-east-1:123:secret:my-secret"}

    with mock.patch.object(secret, "_client", return_value=mock_client):
        assert secret.exists is True
        mock_client.describe_secret.assert_called_once_with(SecretId="my-secret")


def test_exists_false():
    """Test exists returns False when secret does not exist."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_secret.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(secret, "_client", return_value=mock_client):
        assert secret.exists is False


def test_value_json():
    """Test value returns parsed JSON when secret is valid JSON."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": '{"username": "admin", "password": "secret123"}'}

    with mock.patch.object(secret, "_client", return_value=mock_client):
        result = secret.value
        assert result == {"username": "admin", "password": "secret123"}
        mock_client.get_secret_value.assert_called_once_with(SecretId="my-secret")


def test_value_string():
    """Test value returns raw string when secret is not JSON."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": "plain-text-secret"}

    with mock.patch.object(secret, "_client", return_value=mock_client):
        result = secret.value
        assert result == "plain-text-secret"


def test_value_not_found():
    """Test value raises IHSecretNotFound when secret does not exist."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_secret_value.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(secret, "_client", return_value=mock_client):
        with pytest.raises(IHSecretNotFound) as exc_info:
            _ = secret.value
        assert "my-secret" in str(exc_info.value)


def test_create():
    """Test create creates a secret with string value."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.create("my-value", description="Test secret")
        mock_client.create_secret.assert_called_once_with(
            Name="my-secret",
            SecretString="my-value",
            Description="Test secret",
        )


def test_create_json():
    """Test create JSON-encodes dict values."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.create({"username": "admin", "password": "secret123"})
        mock_client.create_secret.assert_called_once_with(
            Name="my-secret",
            SecretString='{"username": "admin", "password": "secret123"}',
        )


def test_delete():
    """Test delete with default options."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.delete()
        mock_client.delete_secret.assert_called_once_with(SecretId="my-secret")


def test_delete_force():
    """Test delete with force=True for immediate deletion."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.delete(force=True)
        mock_client.delete_secret.assert_called_once_with(
            SecretId="my-secret",
            ForceDeleteWithoutRecovery=True,
        )


def test_delete_recovery_window():
    """Test delete with custom recovery window."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.delete(recovery_window_days=30)
        mock_client.delete_secret.assert_called_once_with(
            SecretId="my-secret",
            RecoveryWindowInDays=30,
        )


def test_ensure_present_creates_when_missing():
    """Test ensure_present creates secret when it doesn't exist."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.ensure_present("my-value", description="Test secret")
        mock_client.create_secret.assert_called_once()


def test_ensure_present_skips_when_exists():
    """Test ensure_present does nothing when secret already exists."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.create_secret.side_effect = _make_client_error("ResourceExistsException")

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.ensure_present("my-value")  # Should not raise
        mock_client.create_secret.assert_called_once()
        mock_client.put_secret_value.assert_not_called()


def test_ensure_present_updates_when_exists_and_flag_set():
    """Test ensure_present updates secret when it exists and update_if_exists=True."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.create_secret.side_effect = _make_client_error("ResourceExistsException")

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.ensure_present("new-value", update_if_exists=True)
        mock_client.create_secret.assert_called_once()
        mock_client.put_secret_value.assert_called_once_with(SecretId="my-secret", SecretString="new-value")


def test_ensure_absent_deletes_when_exists():
    """Test ensure_absent deletes secret when it exists."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.ensure_absent(force=True)
        mock_client.delete_secret.assert_called_once_with(
            SecretId="my-secret",
            ForceDeleteWithoutRecovery=True,
        )


def test_ensure_absent_skips_when_missing():
    """Test ensure_absent does nothing when secret doesn't exist."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_secret.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(secret, "_client", return_value=mock_client):
        secret.ensure_absent()  # Should not raise
        mock_client.delete_secret.assert_called_once()


def test_arn():
    """Test arn property returns the secret ARN."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_secret.return_value = {"ARN": "arn:aws:secretsmanager:us-east-1:123:secret:my-secret-abc123"}

    with mock.patch.object(secret, "_client", return_value=mock_client):
        assert secret.arn == "arn:aws:secretsmanager:us-east-1:123:secret:my-secret-abc123"


def test_version_id():
    """Test version_id property returns the version ID."""
    secret = Secret("my-secret", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": "value", "VersionId": "abc-123-def"}

    with mock.patch.object(secret, "_client", return_value=mock_client):
        assert secret.version_id == "abc-123-def"
