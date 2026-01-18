"""Tests for SSO login error handling."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws import _get_credentials
from infrahouse_core.aws.config import AWSConfig
from infrahouse_core.aws.exceptions import IHAWSException


def _make_client_error(code, message="test error"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


@pytest.fixture
def mock_aws_config():
    """Create a mock AWSConfig that returns expected SSO values."""
    config = mock.MagicMock(spec=AWSConfig)
    config.get_start_url.return_value = "https://example.awsapps.com/start"
    config.get_role.return_value = "TestRole"
    config.get_account_id.return_value = "123456789012"
    return config


def test_get_credentials_register_client_error(mock_aws_config):
    """Test _get_credentials raises IHAWSException when register_client fails."""
    mock_sso_oidc = mock.MagicMock()
    mock_sso_oidc.register_client.side_effect = _make_client_error(
        "InvalidClientException", "Client registration failed"
    )

    with mock.patch("infrahouse_core.aws.Session") as mock_session_class:
        mock_session = mock.MagicMock()
        mock_session.client.return_value = mock_sso_oidc
        mock_session_class.return_value = mock_session

        with pytest.raises(IHAWSException) as exc_info:
            _get_credentials(mock_aws_config, "test-profile")

        error_message = str(exc_info.value)
        assert "Failed to register SSO client" in error_message
        assert "test-profile" in error_message
        assert "InvalidClientException" in error_message
        assert "Client registration failed" in error_message


def test_get_credentials_device_authorization_error(mock_aws_config):
    """Test _get_credentials raises IHAWSException when start_device_authorization fails."""
    mock_sso_oidc = mock.MagicMock()
    mock_sso_oidc.register_client.return_value = {
        "clientId": "test-client-id",
        "clientSecret": "test-client-secret",
    }
    mock_sso_oidc.start_device_authorization.side_effect = _make_client_error(
        "InvalidRequestException", "Invalid start URL"
    )

    with mock.patch("infrahouse_core.aws.Session") as mock_session_class:
        mock_session = mock.MagicMock()
        mock_session.client.return_value = mock_sso_oidc
        mock_session_class.return_value = mock_session

        with pytest.raises(IHAWSException) as exc_info:
            _get_credentials(mock_aws_config, "test-profile")

        error_message = str(exc_info.value)
        assert "Failed to start SSO device authorization" in error_message
        assert "test-profile" in error_message
        assert "InvalidRequestException" in error_message
        assert "Invalid start URL" in error_message
        assert "https://example.awsapps.com/start" in error_message


def test_get_credentials_error_with_empty_message(mock_aws_config):
    """Test _get_credentials provides fallback text when AWS returns empty error message."""
    mock_sso_oidc = mock.MagicMock()
    # Simulate an error with empty/missing message
    mock_sso_oidc.register_client.side_effect = ClientError({"Error": {"Code": "UnknownError"}}, "test_operation")

    with mock.patch("infrahouse_core.aws.Session") as mock_session_class:
        mock_session = mock.MagicMock()
        mock_session.client.return_value = mock_sso_oidc
        mock_session_class.return_value = mock_session

        with pytest.raises(IHAWSException) as exc_info:
            _get_credentials(mock_aws_config, "test-profile")

        error_message = str(exc_info.value)
        # Should contain fallback message instead of empty string
        assert "No details provided" in error_message or "UnknownError" in error_message
