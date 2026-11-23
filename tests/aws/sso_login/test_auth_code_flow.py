"""
The authorization-code flow with PKCE, as SSOTokenFetcherAuth and AuthCodeFetcher in the AWS CLI do it.
"""

import base64
import hashlib
import http.client
import socket
import string
import threading
import time
from urllib.parse import parse_qs, parse_qsl, urlsplit

import pytest

from infrahouse_core.aws import aws_sso_login, sso_login
from infrahouse_core.aws.config import AWSConfig
from infrahouse_core.aws.exceptions import IHAWSException

from .conftest import (
    AUTH_CODE,
    CLIENT_ID,
    CLIENT_SECRET,
    OIDC_BASE_URL,
    PROFILE_A,
    callback,
    empty_callback,
    error_callback,
    missing_state_callback,
    other_path,
    write_config,
    wrong_state_callback,
)

VERIFIER_ALPHABET = set(string.ascii_letters + string.digits + "-._~")


@pytest.fixture
def short_timeout(monkeypatch):
    """Wait a fraction of a second for the browser instead of ten minutes."""
    monkeypatch.setattr(sso_login, "_AUTH_CODE_TIMEOUT", 0.5)


def assert_stopped(servers):
    assert servers, "no callback server was created"
    for server in servers:
        assert server.socket.fileno() == -1
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(server.bound_address[:2], timeout=1).close()


def assert_no_device_flow(oidc):
    assert "StartDeviceAuthorization" not in oidc.operations
    assert oidc.operations.count("RegisterClient") == 1


def authorize_params(url: str) -> dict:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


# --- The requests ih-aws sends ---


def test_register_client_parameters(aws_config, oidc, browser):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert oidc.calls_to("RegisterClient") == [
        {
            "clientName": "infrahouse-toolkit",
            "clientType": "public",
            "grantTypes": ["authorization_code", "refresh_token"],
            "redirectUris": ["http://127.0.0.1/oauth/callback"],
            "issuerUrl": "https://example.awsapps.com/start",
            "scopes": ["sso:account:access"],
        }
    ]
    oidc.stubber.assert_no_pending_responses()


def test_register_client_with_configured_scopes(home, oidc, browser):
    write_config(home, scopes="sso:account:access, codewhisperer:completions")
    oidc.expect_pkce_login(scopes=["sso:account:access", "codewhisperer:completions"])

    aws_sso_login(AWSConfig(), PROFILE_A)

    assert oidc.calls_to("RegisterClient")[0]["scopes"] == ["sso:account:access", "codewhisperer:completions"]
    assert authorize_params(browser.authorize_url)["scopes"] == "sso:account:access codewhisperer:completions"


def test_authorize_url(aws_config, oidc, browser, callback_servers):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    url = urlsplit(browser.authorize_url)
    assert f"{url.scheme}://{url.netloc}" == OIDC_BASE_URL
    assert url.path == "/authorize"
    # The parameters, in the order the AWS CLI sends them.
    assert [key for key, _ in parse_qsl(url.query)] == [
        "response_type",
        "client_id",
        "redirect_uri",
        "state",
        "code_challenge_method",
        "scopes",
        "code_challenge",
    ]
    params = authorize_params(browser.authorize_url)
    port = callback_servers[0].bound_address[1]
    assert params["response_type"] == "code"
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == f"http://127.0.0.1:{port}/oauth/callback"
    assert params["code_challenge_method"] == "S256"
    assert params["scopes"] == "sso:account:access"
    assert len(params["state"]) >= 32


def test_code_challenge_is_s256_of_verifier(aws_config, oidc, browser):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    verifier = oidc.calls_to("CreateToken")[0]["codeVerifier"]
    assert len(verifier) == 64
    assert set(verifier) <= VERIFIER_ALPHABET
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
    assert authorize_params(browser.authorize_url)["code_challenge"] == expected


def test_create_token_gets_code_and_redirect_uri_with_port(aws_config, oidc, browser, callback_servers):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    port = callback_servers[0].bound_address[1]
    assert port != 0
    [create_token] = oidc.calls_to("CreateToken")
    assert create_token["grantType"] == "authorization_code"
    assert create_token["clientId"] == CLIENT_ID
    assert create_token["clientSecret"] == CLIENT_SECRET
    assert create_token["code"] == AUTH_CODE
    assert create_token["redirectUri"] == f"http://127.0.0.1:{port}/oauth/callback"
    assert create_token["redirectUri"] == authorize_params(browser.authorize_url)["redirect_uri"]


def test_server_bound_to_loopback(aws_config, oidc, browser, callback_servers):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert len(callback_servers) == 1
    assert callback_servers[0].bound_address[0] == "127.0.0.1"
    assert_stopped(callback_servers)


def test_browser_gets_success_page(aws_config, oidc, browser):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    browser.join()
    [(status, body)] = browser.responses
    assert status == 200
    assert "close this window" in body.lower()


def test_url_printed_to_stderr_not_stdout(aws_config, oidc, browser, capfd):
    """The URL is printed for the user, on stderr, so `eval "$(ih-aws ... credentials -e)"` still works."""
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    out, err = capfd.readouterr()
    assert browser.authorize_url in err
    assert browser.authorize_url not in out
    assert "open this URL" in err


def test_state_and_verifier_differ_between_logins(aws_config, oidc, local_browser):
    first = local_browser()
    oidc.expect_pkce_login()
    aws_sso_login(aws_config, PROFILE_A)
    second = local_browser()
    oidc.expect_pkce_login()
    aws_sso_login(aws_config, PROFILE_A)

    first_params, second_params = authorize_params(first.authorize_url), authorize_params(second.authorize_url)
    assert first_params["state"] != second_params["state"]
    assert first_params["code_challenge"] != second_params["code_challenge"]
    verifiers = [params["codeVerifier"] for params in oidc.calls_to("CreateToken")]
    assert verifiers[0] != verifiers[1]


# --- Requests the callback server rejects and keeps waiting ---


@pytest.mark.parametrize(
    "stray, status",
    [
        (other_path("/favicon.ico"), 404),
        (other_path("/"), 404),
        (other_path("/oauth/callback/extra?code=x"), 404),
        (wrong_state_callback(), 400),
        (missing_state_callback(), 400),
        (wrong_state_callback(error="access_denied"), 400),
        (missing_state_callback(error="access_denied"), 400),
        (empty_callback(), 400),
    ],
    ids=[
        "favicon",
        "root",
        "longer-path",
        "wrong-state",
        "missing-state",
        "wrong-state-with-error",
        "missing-state-with-error",
        "right-state-no-code",
    ],
)
def test_stray_request_then_login_completes(aws_config, oidc, local_browser, callback_servers, stray, status):
    browser = local_browser([stray, callback()])
    oidc.expect_pkce_login()

    session = aws_sso_login(aws_config, PROFILE_A)

    assert session.profile_name == PROFILE_A
    browser.join()
    assert [response[0] for response in browser.responses] == [status, 200]
    assert oidc.calls_to("CreateToken")[0]["code"] == AUTH_CODE
    assert_no_device_flow(oidc)
    assert_stopped(callback_servers)


@pytest.mark.parametrize(
    "stray",
    [wrong_state_callback(), missing_state_callback(), wrong_state_callback(error="access_denied"), empty_callback()],
    ids=["wrong-state", "missing-state", "wrong-state-with-error", "right-state-no-code"],
)
def test_stray_request_alone_times_out(aws_config, oidc, local_browser, callback_servers, short_timeout, stray):
    browser = local_browser([stray])
    oidc.expect_pkce_registration()

    with pytest.raises(IHAWSException, match="use_device_code=True"):
        aws_sso_login(aws_config, PROFILE_A)

    browser.join()
    assert [response[0] for response in browser.responses] == [400]
    assert "CreateToken" not in oidc.operations
    assert_no_device_flow(oidc)
    assert_stopped(callback_servers)


# --- Failures that end the login ---


def test_error_in_callback(aws_config, oidc, local_browser, callback_servers):
    browser = local_browser([error_callback("access_denied", "The user denied the request")])
    oidc.expect_pkce_registration()

    with pytest.raises(IHAWSException, match="access_denied"):
        aws_sso_login(aws_config, PROFILE_A)

    browser.join()
    [(status, body)] = browser.responses
    assert status == 200
    assert "failed" in body.lower()
    assert "CreateToken" not in oidc.operations
    assert_no_device_flow(oidc)
    assert_stopped(callback_servers)


def test_timeout_without_callback(aws_config, oidc, local_browser, callback_servers, short_timeout):
    local_browser([])
    oidc.expect_pkce_registration()
    start = time.monotonic()

    with pytest.raises(IHAWSException, match="use_device_code=True"):
        aws_sso_login(aws_config, PROFILE_A)

    assert 0.4 < time.monotonic() - start < 5
    assert "CreateToken" not in oidc.operations
    assert_no_device_flow(oidc)
    assert_stopped(callback_servers)


def test_timeout_is_the_aws_cli_overall_timeout():
    """AuthCodeFetcher._OVERALL_TIMEOUT is 60 * 10 in the AWS CLI."""
    assert sso_login._AUTH_CODE_TIMEOUT == 600  # pylint: disable=protected-access


def test_create_token_error(aws_config, oidc, browser, callback_servers):
    oidc.expect_pkce_registration()
    oidc.stubber.add_client_error(
        "create_token", service_error_code="InvalidGrantException", service_message="Invalid grant provided"
    )

    with pytest.raises(IHAWSException, match="InvalidGrantException"):
        aws_sso_login(aws_config, PROFILE_A)

    assert_no_device_flow(oidc)
    assert_stopped(callback_servers)


def test_register_client_error(aws_config, oidc, browser, callback_servers):
    oidc.stubber.add_client_error(
        "register_client", service_error_code="InvalidClientMetadataException", service_message="Bad metadata"
    )

    with pytest.raises(IHAWSException, match="Failed to register SSO client for profile 'dev'"):
        aws_sso_login(aws_config, PROFILE_A)

    assert not browser.urls
    assert "StartDeviceAuthorization" not in oidc.operations
    assert_stopped(callback_servers)


# --- Clients that hold a connection open ---


class StallingBrowser:
    """
    Opens a connection to the callback server and holds it, sending a byte now and then or nothing at all.

    It lets go by itself after ``HOLD_SECONDS``, so that a server that waits for it makes the test fail on time instead
    of hanging it.
    """

    HOLD_SECONDS = 4

    def __init__(self, drip: bool, then_callback: bool = False):
        self.drip = drip
        self.then_callback = then_callback
        self.urls = []
        self.status = None
        self._stop = threading.Event()
        self._thread = None

    def __call__(self, url, *args, **kwargs):  # pylint: disable=unused-argument
        self.urls.append(url)
        params = authorize_params(url)
        redirect = urlsplit(params["redirect_uri"])
        self._thread = threading.Thread(
            target=self._run, args=(redirect.hostname, redirect.port, redirect.path, params["state"]), daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        self._thread.join(5)

    def _run(self, host, port, path, state):
        stalled = socket.create_connection((host, port), timeout=5)
        try:
            if self.then_callback:
                threading.Thread(target=self._callback, args=(host, port, path, state), daemon=True).start()
            give_up = time.monotonic() + self.HOLD_SECONDS
            while not self._stop.wait(0.05) and time.monotonic() < give_up:
                if self.drip:
                    try:
                        stalled.sendall(b"G")
                    except OSError:
                        return
        finally:
            stalled.close()

    def _callback(self, host, port, path, state):
        # Give the server time to accept the stalled connection first.
        time.sleep(0.1)
        connection = http.client.HTTPConnection(host, port, timeout=10)
        connection.request("GET", callback()(path, state))
        self.status = connection.getresponse().status
        connection.close()


@pytest.mark.parametrize("drip", [False, True], ids=["silent", "one-byte-at-a-time"])
def test_stalled_connection_does_not_hold_the_wait(
    aws_config, oidc, monkeypatch, local_browser, callback_servers, short_timeout, drip
):
    local_browser()
    stalling = StallingBrowser(drip)
    monkeypatch.setattr("webbrowser.open", stalling)
    oidc.expect_pkce_registration()
    start = time.monotonic()

    try:
        with pytest.raises(IHAWSException, match="use_device_code=True"):
            aws_sso_login(aws_config, PROFILE_A)
    finally:
        stalling.stop()

    assert time.monotonic() - start < 2
    assert_stopped(callback_servers)


@pytest.mark.parametrize("drip", [False, True], ids=["silent", "one-byte-at-a-time"])
def test_stalled_connection_does_not_block_the_callback(
    aws_config, oidc, monkeypatch, local_browser, callback_servers, drip
):
    """A connection that stalls is cut off after the per-connection limit, and the real callback still gets in."""
    monkeypatch.setattr(sso_login, "_AUTH_CODE_TIMEOUT", 10)
    monkeypatch.setattr(sso_login, "_CALLBACK_REQUEST_TIMEOUT", 0.3)
    local_browser()
    stalling = StallingBrowser(drip, then_callback=True)
    monkeypatch.setattr("webbrowser.open", stalling)
    oidc.expect_pkce_login()
    start = time.monotonic()

    try:
        session = aws_sso_login(aws_config, PROFILE_A)
    finally:
        stalling.stop()

    assert session.profile_name == PROFILE_A
    assert stalling.status == 200
    assert time.monotonic() - start < 2
    assert_stopped(callback_servers)


def test_callback_request_timeout_is_the_aws_cli_one():
    """AuthCodeFetcher._REQUEST_TIMEOUT is 10 in the AWS CLI."""
    assert sso_login._CALLBACK_REQUEST_TIMEOUT == 10  # pylint: disable=protected-access
