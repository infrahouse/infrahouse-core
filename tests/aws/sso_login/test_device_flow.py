"""
The device flow, the fallback when no browser on this machine can finish the PKCE flow.
"""

import hashlib
import json
import os
from os import path as osp

import pytest

from infrahouse_core.aws import aws_sso_login
from infrahouse_core.aws.config import AWSConfig
from infrahouse_core.aws.exceptions import IHAWSException

from .conftest import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    PROFILE_A,
    REFRESH_TOKEN,
    SSO_SESSION,
    START_URL,
    USER_CODE,
    VERIFICATION_URI,
    write_config,
)


def token_path(cache_dir: str) -> str:
    return osp.join(cache_dir, hashlib.sha1(SSO_SESSION.encode("utf-8")).hexdigest() + ".json")


@pytest.fixture
def ssh(monkeypatch):
    monkeypatch.setenv("SSH_TTY", "/dev/ttys001")


def test_registers_with_scopes_and_no_grant_types(aws_config, oidc, browser, ssh, no_sleep):
    oidc.expect_device_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert oidc.calls_to("RegisterClient") == [
        {"clientName": "infrahouse-toolkit", "clientType": "public", "scopes": ["sso:account:access"]}
    ]


def test_registers_with_configured_scopes(home, oidc, browser, ssh, no_sleep):
    write_config(home, scopes="sso:account:access,codewhisperer:completions")
    oidc.expect_device_login(scopes=["sso:account:access", "codewhisperer:completions"])

    aws_sso_login(AWSConfig(), PROFILE_A)

    assert oidc.calls_to("RegisterClient")[0]["scopes"] == ["sso:account:access", "codewhisperer:completions"]


def test_polls_until_approved(aws_config, oidc, browser, ssh, no_sleep):
    oidc.expect_device_login(pending=3)

    aws_sso_login(aws_config, PROFILE_A)

    assert oidc.operations == ["RegisterClient", "StartDeviceAuthorization"] + ["CreateToken"] * 4
    assert oidc.calls_to("StartDeviceAuthorization") == [
        {"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET, "startUrl": START_URL}
    ]
    assert no_sleep.call_count == 4
    no_sleep.assert_called_with(5)
    oidc.stubber.assert_no_pending_responses()


def test_prints_url_and_user_code(aws_config, oidc, browser, ssh, no_sleep, capfd):
    """The URL and the code are always printed, on stderr, so the user can approve on another device."""
    oidc.expect_device_login()

    aws_sso_login(aws_config, PROFILE_A)

    out, err = capfd.readouterr()
    assert VERIFICATION_URI in err
    assert USER_CODE in err
    assert USER_CODE not in out


def test_saves_token(aws_config, oidc, browser, ssh, no_sleep, token_cache_dir):
    oidc.expect_device_login()

    aws_sso_login(aws_config, PROFILE_A)

    path = token_path(token_cache_dir)
    with open(path, encoding="utf-8") as token_file:
        token = json.load(token_file)
    assert token["accessToken"] == ACCESS_TOKEN
    assert token["refreshToken"] == REFRESH_TOKEN
    assert token["clientId"] == CLIENT_ID
    assert token["clientSecret"] == CLIENT_SECRET
    assert token["startUrl"] == START_URL
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_not_approved_in_time(aws_config, oidc, browser, ssh, no_sleep, token_cache_dir):
    oidc.expect_device_registration()
    oidc.expect_device_authorization(expires_in=10, interval=5)
    for _ in range(2):
        oidc.stubber.add_client_error("create_token", service_error_code="AuthorizationPendingException")

    with pytest.raises(IHAWSException, match="10 seconds"):
        aws_sso_login(aws_config, PROFILE_A)

    assert not osp.exists(token_path(token_cache_dir))


def test_start_device_authorization_error(aws_config, oidc, browser, ssh):
    oidc.expect_device_registration()
    oidc.stubber.add_client_error(
        "start_device_authorization", service_error_code="InvalidRequestException", service_message="Invalid start URL"
    )

    with pytest.raises(IHAWSException) as exc_info:
        aws_sso_login(aws_config, PROFILE_A)

    message = str(exc_info.value)
    assert "Failed to start SSO device authorization" in message
    assert "'dev'" in message
    assert "InvalidRequestException" in message
    assert "Invalid start URL" in message
    assert START_URL in message


def test_register_client_error(aws_config, oidc, browser, ssh):
    oidc.stubber.add_client_error(
        "register_client", service_error_code="InvalidClientException", service_message="Client registration failed"
    )

    with pytest.raises(IHAWSException) as exc_info:
        aws_sso_login(aws_config, PROFILE_A)

    message = str(exc_info.value)
    assert "Failed to register SSO client" in message
    assert "'dev'" in message
    assert "InvalidClientException" in message
    assert "Client registration failed" in message


def test_error_with_empty_message(aws_config, oidc, browser, ssh):
    """AWS may return an error without a message; the exception then says so instead of being blank."""
    oidc.stubber.add_client_error("register_client", service_error_code="UnknownError", service_message="")

    with pytest.raises(IHAWSException) as exc_info:
        aws_sso_login(aws_config, PROFILE_A)

    assert "UnknownError" in str(exc_info.value)
