"""
aws_sso_login picks the authorization-code flow with PKCE when a browser on this machine can finish it, and the device
flow otherwise. The choice is made before anything is shown to the user.
"""

import errno
import logging
import webbrowser
from unittest import mock

import pytest

from infrahouse_core.aws import aws_sso_login, sso_login

from .conftest import PROFILE_A, VERIFICATION_URI_COMPLETE


def ran_pkce(oidc) -> bool:
    return [params["grantType"] for params in oidc.calls_to("CreateToken")] == ["authorization_code"]


def ran_device_flow(oidc) -> bool:
    return "StartDeviceAuthorization" in oidc.operations and oidc.calls_to("CreateToken")[-1]["grantType"] == (
        "urn:ietf:params:oauth:grant-type:device_code"
    )


def test_macos_local_uses_pkce(aws_config, oidc, browser, no_sleep):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert ran_pkce(oidc)
    # Only Linux may have no browser; webbrowser.get() isn't consulted elsewhere.
    webbrowser.get.assert_not_called()
    oidc.stubber.assert_no_pending_responses()


def test_linux_with_browser_uses_pkce(aws_config, oidc, browser, monkeypatch, no_sleep):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert ran_pkce(oidc)
    webbrowser.get.assert_called_once_with()


@pytest.mark.parametrize("variable, value", [("SSH_CONNECTION", "10.0.0.1 51234 10.0.0.2 22"), ("SSH_TTY", "1")])
def test_ssh_session_uses_device_flow(aws_config, oidc, browser, monkeypatch, no_sleep, variable, value, caplog):
    monkeypatch.setenv(variable, value)
    oidc.expect_device_login()

    with caplog.at_level(logging.INFO, logger="infrahouse_core.aws.sso_login"):
        aws_sso_login(aws_config, PROFILE_A)

    assert ran_device_flow(oidc)
    # No browser opens in an SSH session; the user approves on another device.
    assert not browser.urls
    assert "device" in caplog.text.lower()
    assert variable in caplog.text


def test_linux_without_browser_uses_device_flow(aws_config, oidc, browser, monkeypatch, no_sleep, caplog):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(
        webbrowser, "get", mock.MagicMock(side_effect=webbrowser.Error("could not locate runnable browser"))
    )
    oidc.expect_device_login()

    with caplog.at_level(logging.INFO, logger="infrahouse_core.aws.sso_login"):
        aws_sso_login(aws_config, PROFILE_A)

    assert ran_device_flow(oidc)
    assert not browser.urls
    assert "browser" in caplog.text.lower()


def test_callback_server_cannot_bind_uses_device_flow(aws_config, oidc, browser, monkeypatch, no_sleep, caplog):
    monkeypatch.setattr(
        sso_login._CallbackServer,  # pylint: disable=protected-access
        "server_bind",
        mock.MagicMock(side_effect=OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")),
    )
    oidc.expect_device_login()

    with caplog.at_level(logging.INFO, logger="infrahouse_core.aws.sso_login"):
        aws_sso_login(aws_config, PROFILE_A)

    assert ran_device_flow(oidc)
    # Nothing was registered for PKCE: the server is created first.
    assert oidc.operations.count("RegisterClient") == 1
    assert "callback server" in caplog.text.lower()
    # The browser itself works, so the device flow opens it.
    assert browser.urls == [VERIFICATION_URI_COMPLETE]


def test_browser_does_not_open_uses_device_flow(aws_config, oidc, local_browser, callback_servers, no_sleep, caplog):
    browser = local_browser(opens=False)
    oidc.expect_pkce_registration()
    oidc.expect_device_login()

    with caplog.at_level(logging.INFO, logger="infrahouse_core.aws.sso_login"):
        aws_sso_login(aws_config, PROFILE_A)

    assert ran_device_flow(oidc)
    assert "authorization_code" not in [params["grantType"] for params in oidc.calls_to("CreateToken")]
    # One attempt to open the authorize URL; the device flow doesn't try the browser again.
    assert len(browser.urls) == 1
    assert "/authorize?" in browser.urls[0]
    assert "browser" in caplog.text.lower()
    assert callback_servers[0].socket.fileno() == -1


def test_use_device_code_forces_device_flow(aws_config, oidc, browser, callback_servers, no_sleep, caplog):
    oidc.expect_device_login()

    with caplog.at_level(logging.INFO, logger="infrahouse_core.aws.sso_login"):
        aws_sso_login(aws_config, PROFILE_A, use_device_code=True)

    assert ran_device_flow(oidc)
    assert not callback_servers
    assert "use_device_code" in caplog.text
    # On a laptop the device flow still opens the verification URL in the local browser.
    assert browser.urls == [VERIFICATION_URI_COMPLETE]


def test_pkce_logged_with_reason(aws_config, oidc, browser, caplog):
    oidc.expect_pkce_login()

    with caplog.at_level(logging.INFO, logger="infrahouse_core.aws.sso_login"):
        aws_sso_login(aws_config, PROFILE_A)

    assert "authorization code" in caplog.text.lower()
    assert "pkce" in caplog.text.lower()


def test_positional_region_still_works(aws_config, oidc, browser):
    """Existing calls keep working: aws_sso_login(aws_config, profile_name, region)."""
    oidc.expect_pkce_login()

    assert aws_sso_login(aws_config, PROFILE_A, "ap-south-1").region_name == "ap-south-1"
