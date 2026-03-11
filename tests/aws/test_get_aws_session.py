"""Tests for get_aws_session() profile handling (issue #113)."""

from unittest import mock

from infrahouse_core.aws import get_aws_session
from infrahouse_core.aws.config import AWSConfig


def test_get_aws_session_passes_profile_on_success_path():
    """
    When get_caller_identity() succeeds (SSO token already valid),
    get_aws_session() must return a session with the requested profile_name.

    Regression test for https://github.com/infrahouse/infrahouse-core/issues/113
    """
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["profile-a", "profile-b"]

    with mock.patch("infrahouse_core.aws.get_aws_client") as mock_get_client:
        # Simulate successful get_caller_identity (SSO token is valid)
        mock_sts = mock.MagicMock()
        mock_sts.get_caller_identity.return_value = {"Arn": "arn:aws:iam::123456789012:user/test"}
        mock_get_client.return_value = mock_sts

        with mock.patch("infrahouse_core.aws.boto3.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session_cls.return_value = mock_session

            result = get_aws_session(mock_config, "profile-a", "us-west-2")

            # The key assertion: profile_name must be passed
            mock_session_cls.assert_called_once_with(region_name="us-west-2", profile_name="profile-a")
            assert result is mock_session


def test_get_aws_session_passes_default_profile_when_none():
    """
    When aws_profile is None and 'default' exists in config,
    the session should use 'default' as profile_name.
    """
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["default", "other"]

    with mock.patch("infrahouse_core.aws.get_aws_client") as mock_get_client:
        mock_sts = mock.MagicMock()
        mock_sts.get_caller_identity.return_value = {"Arn": "arn:aws:iam::123456789012:user/test"}
        mock_get_client.return_value = mock_sts

        with mock.patch("infrahouse_core.aws.boto3.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session_cls.return_value = mock_session

            result = get_aws_session(mock_config, None, "us-east-1")

            mock_session_cls.assert_called_once_with(region_name="us-east-1", profile_name="default")
            assert result is mock_session