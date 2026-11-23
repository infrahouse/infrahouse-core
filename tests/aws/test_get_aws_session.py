"""Tests for get_aws_session() profile handling (issue #113)."""

from unittest import mock

import pytest
from botocore.exceptions import (
    ClientError,
    NoRegionError,
    PendingAuthorizationExpiredError,
    SSOError,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

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
    When aws_profile is None, no env credentials, and 'default' exists in config,
    the session should use 'default' as profile_name.
    """
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["default", "other"]

    env_patch = mock.patch.dict("os.environ", {}, clear=True)
    with env_patch, mock.patch("infrahouse_core.aws.get_aws_client") as mock_get_client:
        mock_sts = mock.MagicMock()
        mock_sts.get_caller_identity.return_value = {"Arn": "arn:aws:iam::123456789012:user/test"}
        mock_get_client.return_value = mock_sts

        with mock.patch("infrahouse_core.aws.boto3.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session_cls.return_value = mock_session

            result = get_aws_session(mock_config, None, "us-east-1")

            mock_session_cls.assert_called_once_with(region_name="us-east-1", profile_name="default")
            assert result is mock_session


def test_get_aws_session_env_credentials_override_default_profile():
    """
    When aws_profile is None but AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
    are set in the environment, the default profile must NOT be used.

    Regression test for https://github.com/infrahouse/infrahouse-core/issues/115
    """
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["default", "other"]

    env_vars = {
        "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "AWS_SESSION_TOKEN": "FwoGZXIvYXdzEBYaDCmphExample",
    }
    env_patch = mock.patch.dict("os.environ", env_vars, clear=True)
    with env_patch, mock.patch("infrahouse_core.aws.get_aws_client") as mock_get_client:
        mock_sts = mock.MagicMock()
        mock_sts.get_caller_identity.return_value = {"Arn": "arn:aws:sts::123456789012:assumed-role/MyRole/session"}
        mock_get_client.return_value = mock_sts

        with mock.patch("infrahouse_core.aws.boto3.Session") as mock_session_cls:
            mock_session = mock.MagicMock()
            mock_session_cls.return_value = mock_session

            result = get_aws_session(mock_config, None, "us-west-1")

            # profile_name must be None so boto3 uses env credentials
            mock_session_cls.assert_called_once_with(region_name="us-west-1", profile_name=None)
            assert result is mock_session


# --- Falling back to aws_sso_login (issue #141) ---

SSO_ERRORS = [
    pytest.param(SSOTokenLoadError(error_msg="Token for my-sso does not exist"), id="SSOTokenLoadError"),
    pytest.param(UnauthorizedSSOTokenError(), id="UnauthorizedSSOTokenError"),
    pytest.param(SSOError(), id="SSOError"),
    pytest.param(
        TokenRetrievalError(provider="sso", error_msg="Token has expired and refresh failed"), id="TokenRetrievalError"
    ),
]

OTHER_ERRORS = [
    # A token file that isn't JSON, or that holds `null`: see tests/aws/sso_login/test_botocore_contract.py.
    pytest.param(KeyError("0123abcd"), id="KeyError"),
    pytest.param(TypeError("argument of type 'NoneType' is not iterable"), id="TypeError"),
    pytest.param(
        ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetCallerIdentity"), id="ClientError"
    ),
    pytest.param(NoRegionError(), id="NoRegionError"),
    pytest.param(PendingAuthorizationExpiredError(), id="PendingAuthorizationExpiredError"),
]


def _sts_clients(first_error):
    """get_aws_client() side effect: the first STS call fails, the call with the SSO session succeeds."""
    failing = mock.MagicMock()
    failing.get_caller_identity.side_effect = first_error
    working = mock.MagicMock()
    working.get_caller_identity.return_value = {"Arn": "arn:aws:sts::123456789012:assumed-role/Admin/me"}
    return [failing, working]


@pytest.mark.parametrize("error", SSO_ERRORS)
@pytest.mark.parametrize("use_device_code", [False, True])
def test_get_aws_session_falls_back_to_sso_login(error, use_device_code):
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["dev", "prod"]
    sso_session = mock.MagicMock(name="sso session")

    with (
        mock.patch("infrahouse_core.aws.get_aws_client", side_effect=_sts_clients(error)) as get_client,
        mock.patch("infrahouse_core.aws.aws_sso_login", return_value=sso_session) as login,
    ):
        result = get_aws_session(mock_config, "dev", "us-west-2", use_device_code=use_device_code)

    assert result is sso_session
    login.assert_called_once_with(mock_config, "dev", region="us-west-2", use_device_code=use_device_code)
    assert get_client.call_args_list[1] == mock.call("sts", "dev", "us-west-2", session=sso_session)


def test_get_aws_session_use_device_code_defaults_to_false():
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["dev"]

    with (
        mock.patch(
            "infrahouse_core.aws.get_aws_client", side_effect=_sts_clients(SSOTokenLoadError(error_msg="missing"))
        ),
        mock.patch("infrahouse_core.aws.aws_sso_login") as login,
    ):
        get_aws_session(mock_config, "dev", "us-west-2")

    login.assert_called_once_with(mock_config, "dev", region="us-west-2", use_device_code=False)


@pytest.mark.parametrize("error", OTHER_ERRORS)
def test_get_aws_session_does_not_fall_back_on_other_errors(error):
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["dev"]

    with (
        mock.patch("infrahouse_core.aws.get_aws_client", side_effect=_sts_clients(error)),
        mock.patch("infrahouse_core.aws.aws_sso_login") as login,
    ):
        with pytest.raises(type(error)):
            get_aws_session(mock_config, "dev", "us-west-2")

    login.assert_not_called()


@pytest.mark.parametrize("error", SSO_ERRORS)
def test_get_aws_session_without_profile_exits(error):
    """With no profile there is nothing to log in to; ih-aws asks for --aws-profile, as before."""
    mock_config = mock.MagicMock(spec=AWSConfig)
    mock_config.profiles = ["dev", "prod"]

    with (
        mock.patch.dict("os.environ", {}, clear=True),
        mock.patch("infrahouse_core.aws.get_aws_client", side_effect=_sts_clients(error)),
        mock.patch("infrahouse_core.aws.aws_sso_login") as login,
    ):
        with pytest.raises(SystemExit):
            get_aws_session(mock_config, None, "us-west-2")

    login.assert_not_called()
