"""
No log line or printed line, at any level, shows a token, a client secret, a device code, an authorization code or a
code verifier.
"""

import logging

import pytest

from infrahouse_core.aws import aws_sso_login
from infrahouse_core.aws.exceptions import IHAWSException

from .conftest import (
    PROFILE_A,
    SECRETS,
    USER_CODE,
    VERIFICATION_URI,
    callback,
    error_callback,
    missing_state_callback,
    other_path,
    wrong_state_callback,
)


@pytest.fixture
def debug_logging(caplog):
    """Debug logging on for everything, botocore included."""
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="botocore")
    caplog.set_level(logging.DEBUG, logger="infrahouse_core")
    return caplog


def assert_no_secrets(texts, extra=()):
    for text in texts:
        for secret in tuple(SECRETS) + tuple(extra):
            assert secret not in text


def test_pkce_login_shows_no_secrets(aws_config, oidc, local_browser, debug_logging, capfd):
    browser = local_browser([other_path(), wrong_state_callback(), missing_state_callback(), callback()])
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    browser.join()
    verifier = oidc.calls_to("CreateToken")[0]["codeVerifier"]
    out, err = capfd.readouterr()
    assert debug_logging.text
    assert_no_secrets([debug_logging.text, out, err], extra=[verifier])
    # The authorize URL is fine to show; it holds the challenge, not the verifier.
    assert browser.authorize_url in err


def test_failed_pkce_login_shows_no_secrets(aws_config, oidc, local_browser, debug_logging, capfd):
    browser = local_browser([error_callback()])
    oidc.expect_pkce_registration()

    with pytest.raises(IHAWSException) as exc_info:
        aws_sso_login(aws_config, PROFILE_A)

    browser.join()
    out, err = capfd.readouterr()
    assert_no_secrets([debug_logging.text, out, err, str(exc_info.value)])


def test_device_login_shows_no_secrets(aws_config, oidc, browser, debug_logging, capfd, monkeypatch, no_sleep):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.1 51234 10.0.0.2 22")
    oidc.expect_device_login(pending=2)

    aws_sso_login(aws_config, PROFILE_A)

    out, err = capfd.readouterr()
    assert_no_secrets([debug_logging.text, out, err])
    # The user code and the verification URL are fine to show, and needed.
    assert USER_CODE in err
    assert VERIFICATION_URI in err
