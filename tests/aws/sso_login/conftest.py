"""
Fixtures for the SSO login tests.

Every test runs with ``HOME`` pointing at a temporary directory that holds an ``~/.aws/config`` with one sso-session
and two profiles. botocore reads its SSO token cache directory once, at import time, so the fixtures also point both
of botocore's copies of it at the temporary home. The sso-oidc client is a real botocore client with a Stubber, so the
parameters ih-aws sends are checked against the service model, and no request leaves the process. webbrowser is
patched, so no browser opens.
"""

import http.client
import os
import threading
import time
import webbrowser
from os import path as osp
from textwrap import dedent
from typing import Callable, List, Optional, Tuple
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlsplit

import boto3
import pytest
from botocore import UNSIGNED
from botocore.config import Config
from botocore.credentials import SSOProvider
from botocore.stub import ANY, Stubber
from botocore.tokens import SSOTokenProvider

from infrahouse_core.aws import sso_login
from infrahouse_core.aws.config import AWSConfig

START_URL = "https://example.awsapps.com/start"
SSO_SESSION = "my-sso"
SSO_REGION = "us-west-1"
PROFILE_A = "dev"
PROFILE_B = "prod"
ACCOUNT_A = "111111111111"
ACCOUNT_B = "222222222222"
OIDC_BASE_URL = "https://oidc.us-west-1.amazonaws.com"

# Values the stubs return. Each secret is distinctive, so a test can look for it in logs and output.
CLIENT_ID = "stub-client-id-6b2f"
CLIENT_SECRET = "stub-client-secret-91ad"
ACCESS_TOKEN = "stub-access-token-c37e"
REFRESH_TOKEN = "stub-refresh-token-48f0"
DEVICE_CODE = "stub-device-code-d15a"
AUTH_CODE = "stub-auth-code-7e9c"
USER_CODE = "WXYZ-ABCD"
VERIFICATION_URI = "https://device.sso.us-west-1.amazonaws.com/"
VERIFICATION_URI_COMPLETE = f"{VERIFICATION_URI}?user_code={USER_CODE}"
TOKEN_EXPIRES_IN = 28800
# Registrations last 90 days. RegisterClient returns the expiry in epoch seconds.
CLIENT_SECRET_EXPIRES_AT = int(time.time()) + 90 * 24 * 3600

SECRETS = (CLIENT_SECRET, ACCESS_TOKEN, REFRESH_TOKEN, DEVICE_CODE, AUTH_CODE)

DEFAULT_SCOPES = ["sso:account:access"]
REDIRECT_URI_WITHOUT_PORT = "http://127.0.0.1/oauth/callback"

AWS_ENVIRONMENT = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_USE_FIPS_ENDPOINT",
    "AWS_USE_DUALSTACK_ENDPOINT",
    "SSH_CONNECTION",
    "SSH_TTY",
)


def config_text(scopes: Optional[str] = None) -> str:
    """The test's ~/.aws/config: one sso-session and two profiles of it."""
    scopes_line = f"sso_registration_scopes = {scopes}" if scopes is not None else ""
    return dedent(f"""
        [sso-session {SSO_SESSION}]
        sso_start_url = {START_URL}
        sso_region = {SSO_REGION}
        {scopes_line}

        [profile {PROFILE_A}]
        sso_session = {SSO_SESSION}
        sso_account_id = {ACCOUNT_A}
        sso_role_name = AdministratorAccess
        region = us-east-2

        [profile {PROFILE_B}]
        sso_session = {SSO_SESSION}
        sso_account_id = {ACCOUNT_B}
        sso_role_name = ReadOnlyAccess
        region = us-east-1
        """)


@pytest.fixture
def home(tmp_path, monkeypatch) -> str:
    """
    A fake home directory with no AWS files yet.

    HOME points at it, every AWS and SSH variable is unset, and botocore's two import-time copies of the SSO token
    cache directory point into it, so no test reads or writes the real ``~/.aws``.
    """
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    for name in AWS_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    cache_dir = osp.join(str(home_dir), ".aws", "sso", "cache")
    monkeypatch.setattr(SSOTokenProvider, "_SSO_TOKEN_CACHE_DIR", cache_dir)
    monkeypatch.setattr(SSOProvider, "_SSO_TOKEN_CACHE_DIR", cache_dir)
    return str(home_dir)


@pytest.fixture
def token_cache_dir(home) -> str:
    """Where botocore looks for SSO tokens: ``~/.aws/sso/cache`` in the fake home."""
    return osp.join(home, ".aws", "sso", "cache")


@pytest.fixture
def aws_config(home) -> AWSConfig:
    """An AWSConfig for ``~/.aws/config`` in the fake home, with no ``sso_registration_scopes``."""
    write_config(home)
    return AWSConfig()


def write_config(home: str, scopes: Optional[str] = None) -> None:
    """Write ``~/.aws/config`` in the fake home."""
    aws_dir = osp.join(home, ".aws")
    if not osp.isdir(aws_dir):
        # Like `aws configure` would: ~/.aws with the default mode.
        os.mkdir(aws_dir)
    with open(osp.join(aws_dir, "config"), "w", encoding="utf-8") as config_file:
        config_file.write(config_text(scopes))


def register_response() -> dict:
    return {
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET,
        "clientIdIssuedAt": CLIENT_SECRET_EXPIRES_AT - 90 * 24 * 3600,
        "clientSecretExpiresAt": CLIENT_SECRET_EXPIRES_AT,
    }


def token_response(refresh_token: bool = True) -> dict:
    response = {"accessToken": ACCESS_TOKEN, "tokenType": "Bearer", "expiresIn": TOKEN_EXPIRES_IN}
    if refresh_token:
        response["refreshToken"] = REFRESH_TOKEN
    return response


class OIDCStub:
    """
    A real sso-oidc client with a botocore Stubber, plus a record of every call and its parameters.

    The ``expect_*`` methods queue the responses for one login. The Stubber rejects any call that has no queued
    response, and any parameters that differ from the expected ones.
    """

    def __init__(self):
        self.client = boto3.Session().client(
            "sso-oidc", region_name=SSO_REGION, config=Config(signature_version=UNSIGNED)
        )
        self.calls: List[Tuple[str, dict]] = []
        self.client.meta.events.register("provide-client-params.sso-oidc", self._record)
        self.stubber = Stubber(self.client)
        self.stubber.activate()

    def calls_to(self, operation: str) -> List[dict]:
        """Parameters of every call to ``operation``, e.g. ``CreateToken``, in order."""
        return [params for name, params in self.calls if name == operation]

    @property
    def operations(self) -> List[str]:
        return [name for name, _ in self.calls]

    def expect_pkce_registration(self, scopes: Optional[List[str]] = None) -> None:
        self.stubber.add_response(
            "register_client",
            register_response(),
            expected_params={
                "clientName": "infrahouse-toolkit",
                "clientType": "public",
                "grantTypes": ["authorization_code", "refresh_token"],
                "redirectUris": [REDIRECT_URI_WITHOUT_PORT],
                "issuerUrl": START_URL,
                "scopes": scopes or DEFAULT_SCOPES,
            },
        )

    def expect_pkce_token(self, refresh_token: bool = True) -> None:
        self.stubber.add_response(
            "create_token",
            token_response(refresh_token),
            expected_params={
                "grantType": "authorization_code",
                "clientId": CLIENT_ID,
                "clientSecret": CLIENT_SECRET,
                "code": AUTH_CODE,
                "codeVerifier": ANY,
                "redirectUri": ANY,
            },
        )

    def expect_pkce_login(self, scopes: Optional[List[str]] = None, refresh_token: bool = True) -> None:
        self.expect_pkce_registration(scopes)
        self.expect_pkce_token(refresh_token)

    def expect_device_registration(self, scopes: Optional[List[str]] = None) -> None:
        self.stubber.add_response(
            "register_client",
            register_response(),
            expected_params={
                "clientName": "infrahouse-toolkit",
                "clientType": "public",
                "scopes": scopes or DEFAULT_SCOPES,
            },
        )

    def expect_device_authorization(self, expires_in: int = 600, interval: int = 5) -> None:
        self.stubber.add_response(
            "start_device_authorization",
            {
                "deviceCode": DEVICE_CODE,
                "userCode": USER_CODE,
                "verificationUri": VERIFICATION_URI,
                "verificationUriComplete": VERIFICATION_URI_COMPLETE,
                "expiresIn": expires_in,
                "interval": interval,
            },
            expected_params={"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET, "startUrl": START_URL},
        )

    def expect_device_token(self, pending: int = 1, refresh_token: bool = True) -> None:
        expected = {
            "grantType": "urn:ietf:params:oauth:grant-type:device_code",
            "deviceCode": DEVICE_CODE,
            "clientId": CLIENT_ID,
            "clientSecret": CLIENT_SECRET,
        }
        for _ in range(pending):
            self.stubber.add_client_error(
                "create_token",
                service_error_code="AuthorizationPendingException",
                service_message="Authorization is pending",
                http_status_code=400,
                expected_params=expected,
            )
        self.stubber.add_response("create_token", token_response(refresh_token), expected_params=expected)

    def expect_device_login(self, scopes: Optional[List[str]] = None, pending: int = 1) -> None:
        self.expect_device_registration(scopes)
        self.expect_device_authorization()
        self.expect_device_token(pending)

    def _record(self, params, model, **kwargs):  # pylint: disable=unused-argument
        self.calls.append((model.name, dict(params)))


@pytest.fixture
def oidc(home, monkeypatch) -> OIDCStub:
    """
    The stubbed sso-oidc client that aws_sso_login gets.

    The base URL of the authorize endpoint is fixed here, because botocore's Stubber can't share a client with the
    short-circuited request that finds it. test_oidc_base_url.py tests the real lookup.
    """
    stub = OIDCStub()

    def get_client(region: str):
        assert region == SSO_REGION
        return stub.client

    def get_base_url(client) -> str:
        assert client is stub.client
        return OIDC_BASE_URL

    monkeypatch.setattr(sso_login, "_get_sso_oidc_client", get_client)
    monkeypatch.setattr(sso_login, "_get_oidc_base_url", get_base_url)
    return stub


# --- The browser ---

Request = Callable[[str, str], str]
"""Makes the path and query of one browser request from the redirect URI's path and the expected state."""


def callback(code: str = AUTH_CODE) -> Request:
    """The redirect AWS sends after the user approves."""
    return lambda path, state: f"{path}?{urlencode({'code': code, 'state': state})}"


def error_callback(error: str = "access_denied", description: str = "The user denied the request") -> Request:
    """The redirect AWS sends when the user denies the request."""
    return lambda path, state: f"{path}?{urlencode({'error': error, 'error_description': description, 'state': state})}"


def wrong_state_callback(**extra: str) -> Request:
    return lambda path, state: f"{path}?{urlencode({'code': AUTH_CODE, 'state': 'not-' + state, **extra})}"


def missing_state_callback(**extra: str) -> Request:
    return lambda path, state: f"{path}?{urlencode({'code': AUTH_CODE, **extra})}"


def empty_callback() -> Request:
    """The right state, but neither code nor error."""
    return lambda path, state: f"{path}?{urlencode({'state': state})}"


def other_path(other: str = "/favicon.ico") -> Request:
    return lambda path, state: other


class FakeBrowser:
    """
    Stands in for ``webbrowser.open``.

    When the authorize URL is opened, a thread sends ``requests`` to the redirect URI in it, one connection each, like a
    browser would after the user approves. Each response is kept as ``(status, body)``, or ``(None, error)`` when the
    connection fails.
    """

    def __init__(self, requests: Optional[List[Request]] = None, opens: bool = True):
        self.requests = [callback()] if requests is None else requests
        self.opens = opens
        self.urls: List[str] = []
        self.responses: List[Tuple[Optional[int], str]] = []
        self._thread: Optional[threading.Thread] = None

    def __call__(self, url: str, *args, **kwargs) -> bool:  # pylint: disable=unused-argument
        self.urls.append(url)
        if not self.opens:
            return False
        query = parse_qs(urlsplit(url).query)
        if "redirect_uri" in query:
            redirect = urlsplit(query["redirect_uri"][0])
            self._thread = threading.Thread(
                target=self._send,
                args=(redirect.hostname, redirect.port, redirect.path, query["state"][0]),
                daemon=True,
            )
            self._thread.start()
        return True

    @property
    def authorize_url(self) -> str:
        return self.urls[0]

    def join(self) -> None:
        if self._thread is not None:
            self._thread.join(10)
            assert not self._thread.is_alive()

    def _send(self, host: str, port: int, path: str, state: str) -> None:
        for request in self.requests:
            try:
                connection = http.client.HTTPConnection(host, port, timeout=5)
                connection.request("GET", request(path, state))
                response = connection.getresponse()
                self.responses.append((response.status, response.read().decode()))
                connection.close()
            except OSError as err:
                self.responses.append((None, repr(err)))


@pytest.fixture
def local_browser(monkeypatch):
    """
    A laptop with a local browser: macOS, no SSH session. Returns a function that installs a FakeBrowser.
    """
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(webbrowser, "get", mock.MagicMock(name="webbrowser.get"))

    def install(requests: Optional[List[Request]] = None, opens: bool = True) -> FakeBrowser:
        browser = FakeBrowser(requests, opens)
        monkeypatch.setattr(webbrowser, "open", browser)
        return browser

    return install


@pytest.fixture
def browser(local_browser) -> FakeBrowser:
    """A local browser that sends the approved redirect."""
    return local_browser()


@pytest.fixture
def callback_servers(monkeypatch) -> list:
    """Every callback server aws_sso_login creates, with the address it was bound to."""
    created = []

    class RecordingServer(sso_login._CallbackServer):  # pylint: disable=protected-access
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.bound_address = self.socket.getsockname()
            created.append(self)

    monkeypatch.setattr(sso_login, "_CallbackServer", RecordingServer)
    return created


@pytest.fixture
def no_sleep(monkeypatch):
    """The device flow polls without waiting."""
    sleeper = mock.MagicMock(name="sleep")
    monkeypatch.setattr(sso_login, "sleep", sleeper)
    return sleeper
