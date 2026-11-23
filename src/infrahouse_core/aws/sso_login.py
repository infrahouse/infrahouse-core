"""
SSO login for AWS profiles that use an ``sso-session``.

:func:`aws_sso_login` logs in to AWS IAM Identity Center and saves the SSO access token to the AWS CLI's shared token
cache, ``~/.aws/sso/cache``, in botocore's own format and through botocore's own classes. ``aws sso login`` writes the
same file. botocore, and so ``aws`` and terraform, then find the token for every profile of that sso-session, refresh
it when it is close to expiry, and exchange it for each profile's role credentials. ih-aws keeps no role credentials of
its own.

Two login flows are used, as in the AWS CLI v2:

- The authorization-code flow with PKCE, the default of ``aws sso login`` since AWS CLI 2.22.0. The browser on this
  machine hands the result back to a local server on 127.0.0.1, so only the machine where the user approves gets the
  token. The user sees no code.
- The device flow, when no browser on this machine can finish the PKCE flow, or when the caller asks for it. The user
  opens a URL on any device and enters a code.
"""

import base64
import hashlib
import hmac
import os
import platform
import secrets
import socket
import string
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from json import dumps
from logging import getLogger
from time import monotonic, sleep
from typing import Any, Dict, List, NamedTuple, Optional
from urllib.parse import parse_qs, urlsplit

from boto3 import Session
from botocore import UNSIGNED
from botocore.awsrequest import AWSResponse
from botocore.config import Config
from botocore.exceptions import ClientError
from botocore.utils import JSONFileCache, SSOTokenLoader, percent_encode_sequence

from infrahouse_core.aws.config import AWSConfig
from infrahouse_core.aws.exceptions import IHAWSException

LOG = getLogger(__name__)

# How long, in seconds, to wait for the browser to hand back the authorization code: as long as the AWS CLI waits
# (AuthCodeFetcher._OVERALL_TIMEOUT).
_AUTH_CODE_TIMEOUT = 600
# The longest, in seconds, that any one connection to the callback server may take, so that no client can hold up the
# wait (AuthCodeFetcher._REQUEST_TIMEOUT in the AWS CLI).
_CALLBACK_REQUEST_TIMEOUT = 10
# A socket timeout of 0 would make the connection non-blocking, so a connection always gets at least this long.
_MIN_READ_TIMEOUT = 0.01

_CALLBACK_HOST = "127.0.0.1"
_CALLBACK_PATH = "/oauth/callback"
# The client is registered with the redirect URI without a port. The authorize request and create_token give the port.
_REDIRECT_URI_WITHOUT_PORT = f"http://{_CALLBACK_HOST}{_CALLBACK_PATH}"

_CLIENT_NAME = "infrahouse-toolkit"
_AUTH_CODE_GRANT_TYPES = ["authorization_code", "refresh_token"]
_DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
# Used when the sso-session has no sso_registration_scopes. IAM Identity Center returns a refresh token only for this
# scope or more.
_DEFAULT_SCOPES = ["sso:account:access"]

_CODE_VERIFIER_ALPHABET = string.ascii_letters + string.digits + "-._~"
_CODE_VERIFIER_LENGTH = 64
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class _Login(NamedTuple):
    """What both login flows need to know about the profile being logged in."""

    profile_name: str
    start_url: str
    sso_region: str
    scopes: List[str]
    sso_oidc: Any


class _AuthCodeFlowUnavailable(Exception):
    """
    The PKCE flow can't run here, and nothing has been shown to the user yet. The device flow runs instead.

    :param reason: Why, for the log.
    :param browser_works: Whether the device flow may still open the verification URL in the local browser.
    """

    def __init__(self, reason: str, browser_works: bool):
        super().__init__(reason)
        self.reason = reason
        self.browser_works = browser_works


def aws_sso_login(
    aws_config: AWSConfig,
    profile_name: str,
    region: Optional[str] = None,
    use_device_code: bool = False,
) -> Session:
    """
    Log in to AWS IAM Identity Center for a profile, and save the SSO token where botocore finds it.

    The token goes to ``~/.aws/sso/cache/<sha1 of the sso-session name>.json``, the AWS CLI's shared token cache, in
    botocore's format. ``aws sso login`` writes the same file. botocore, ``aws`` and terraform share it: after one
    login, every profile of the same sso-session works without another approval, until the token expires and can't be
    refreshed. If the cache directory doesn't exist, it is created, with any missing parents, with mode 0700. The token
    file itself is mode 0600. ih-aws doesn't cache role credentials; botocore gets them from the token.

    Every login registers a new OIDC client, and the login runs one of two flows:

    - **Authorization code with PKCE**, the default. ih-aws opens the authorize URL in the local browser, prints it to
      stderr too, and waits up to ten minutes for the browser to come back to a server on 127.0.0.1. The user sees no
      code.
    - **Device flow.** ih-aws prints a verification URL and a code to stderr, and the user approves on any device. It
      runs when ``use_device_code`` is true; in an SSH session (``SSH_CONNECTION`` or ``SSH_TTY`` is set); on Linux
      when ``webbrowser.get()`` finds no browser; and when the local callback server can't start or
      ``webbrowser.open()`` returns false. Each of these is known before the user is asked to approve anything.

    If the browser opens but no answer arrives in time, ih-aws raises instead of starting the device flow, because the
    user may already have approved.

    :param aws_config: AWS config with the profile's SSO settings.
    :type aws_config: AWSConfig
    :param profile_name: AWS profile to log in with. It must have an ``sso_session``.
    :type profile_name: str
    :param region: Region for the returned session. Defaults to the profile's region.
    :type region: str
    :param use_device_code: Use the device flow even if a local browser could finish the PKCE flow, e.g. to
        approve on another device.
    :type use_device_code: bool
    :return: A session for the profile. botocore authenticates it from the saved token.
    :rtype: Session
    :raise IHAWSException: If the login fails, is denied, or isn't approved in time.
    :raise OSError: If the token cache directory or file can't be written.
    """
    start_url = aws_config.get_start_url(profile_name)
    session_name = aws_config.get_sso_session(profile_name)
    sso_region = aws_config.get_sso_region(profile_name)
    scopes = aws_config.get_sso_registration_scopes(profile_name) or list(_DEFAULT_SCOPES)
    cache_dir = _sso_token_cache_dir()
    # Before the login, so that a cache that can't be written fails before the user approves anything.
    _make_private_dirs(cache_dir)
    login = _Login(profile_name, start_url, sso_region, scopes, _get_sso_oidc_client(sso_region))

    token = _log_in(login, use_device_code)

    SSOTokenLoader(JSONFileCache(cache_dir, dumps_func=_dump_sso_token)).save_token(
        login.start_url, token, session_name=session_name
    )
    LOG.info(
        "Saved the SSO token for sso-session %s in %s. It expires at %s.",
        session_name,
        cache_dir,
        token["expiresAt"].strftime(_UTC_FORMAT),
    )
    return Session(profile_name=profile_name, region_name=region or aws_config.get_region(profile_name))


def _log_in(login: _Login, use_device_code: bool) -> dict:
    """Pick the login flow, run it, and return the token to save."""
    browser_problem = _local_browser_problem()
    if use_device_code:
        return _device_code_login(login, "use_device_code=True was passed", open_browser=browser_problem is None)
    if browser_problem is not None:
        return _device_code_login(login, browser_problem, open_browser=False)

    LOG.info("Logging in with the authorization code flow (PKCE), in the browser on this machine.")
    try:
        return _auth_code_login(login)
    except _AuthCodeFlowUnavailable as unavailable:
        return _device_code_login(login, unavailable.reason, open_browser=unavailable.browser_works)


def _local_browser_problem() -> Optional[str]:
    """
    Tell why no browser on this machine can finish the PKCE flow.

    :return: The reason, or None if a local browser can finish it.
    """
    for variable in ("SSH_CONNECTION", "SSH_TTY"):
        if variable in os.environ:
            return f"{variable} is set: this is an SSH session, so the browser isn't on this machine"
    # Only Linux may have no browser at all. The Azure CLI decides the same way (can_launch_browser).
    if platform.system() == "Linux":
        try:
            webbrowser.get()
        except webbrowser.Error:
            return "no web browser was found on this machine"
    return None


# --- Authorization code with PKCE ---


def _auth_code_login(login: _Login) -> dict:
    """
    Log in with the authorization-code flow with PKCE, as the AWS CLI's SSOTokenFetcherAuth does.

    :return: The token to save.
    :raise _AuthCodeFlowUnavailable: If the flow can't start: the callback server can't bind, or the browser can't be
        opened. Nothing has been shown to the user then.
    :raise IHAWSException: If the login fails, is denied, or the browser doesn't come back in time.
    """
    try:
        server = _CallbackServer()
    except OSError as err:
        raise _AuthCodeFlowUnavailable(f"the local callback server can't start ({err})", browser_works=True) from err

    try:
        redirect_uri = f"http://{_CALLBACK_HOST}:{server.server_port}{_CALLBACK_PATH}"
        registration = _register_client(
            login,
            grantTypes=list(_AUTH_CODE_GRANT_TYPES),
            redirectUris=[_REDIRECT_URI_WITHOUT_PORT],
            issuerUrl=login.start_url,
        )
        code_verifier = "".join(secrets.choice(_CODE_VERIFIER_ALPHABET) for _ in range(_CODE_VERIFIER_LENGTH))
        state = secrets.token_urlsafe(32)
        url = _authorize_url(login, registration["clientId"], redirect_uri, state, _code_challenge(code_verifier))

        if not webbrowser.open(url):
            raise _AuthCodeFlowUnavailable("the web browser could not be opened", browser_works=False)
        print(
            "Your browser should open to approve the AWS SSO login. If it doesn't, open this URL in a browser on this"
            f" machine:\n\n    {url}\n",
            file=sys.stderr,
        )
        LOG.info("Waiting up to %d seconds for the browser to return to %s.", _AUTH_CODE_TIMEOUT, redirect_uri)
        code = server.wait_for_code(state, deadline=monotonic() + _AUTH_CODE_TIMEOUT)
    finally:
        server.server_close()

    try:
        response = login.sso_oidc.create_token(
            grantType="authorization_code",
            clientId=registration["clientId"],
            clientSecret=registration["clientSecret"],
            code=code,
            codeVerifier=code_verifier,
            redirectUri=redirect_uri,
        )
    except ClientError as err:
        raise IHAWSException(
            f"Failed to create an SSO token for profile '{login.profile_name}': {_format_client_error(err)}"
        ) from err
    return _make_token(login, registration, response)


def _authorize_url(login: _Login, client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    """
    Build the URL the browser opens to approve the login, as the AWS CLI's ``_get_authorization_uri`` does.

    :return: ``<sso-oidc endpoint>/authorize?...``, with the parameters in the AWS CLI's order.
    """
    query = percent_encode_sequence(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge_method": "S256",
            # Space-separated in the query, unlike in register_client.
            "scopes": " ".join(login.scopes),
        }
    )
    # The challenge is base64url, so it needs no encoding.
    return f"{_get_oidc_base_url(login.sso_oidc)}/authorize?{query}&code_challenge={code_challenge}"


def _code_challenge(code_verifier: str) -> str:
    """The S256 PKCE challenge for a verifier: base64url of its SHA-256, without padding."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _get_oidc_base_url(sso_oidc: Any) -> str:
    """
    Find the base URL of the client's SSO OIDC endpoint, e.g. ``https://oidc.us-west-1.amazonaws.com``.

    The authorize endpoint isn't in the sso-oidc service model. So, as the AWS CLI does
    (``SSOTokenFetcherAuth._get_base_authorization_uri``), botocore resolves the endpoint of a RegisterClient request,
    and the request is stopped before it is sent. This honours the client's region, FIPS and dual-stack settings.

    :param sso_oidc: A botocore sso-oidc client.
    :return: The scheme and host of the endpoint.
    """
    resolved: Dict[str, str] = {}

    def short_circuit(params: dict, **_: Any) -> tuple:
        url = urlsplit(params["url"])
        resolved["base_url"] = f"{url.scheme}://{url.netloc}"
        # A response tuple from a before-call handler takes the place of the request.
        return AWSResponse(None, 200, {}, None), {}

    event = "before-call.sso-oidc.RegisterClient"
    sso_oidc.meta.events.register(event, short_circuit)
    try:
        sso_oidc.register_client(clientName="temp", clientType="public")
    finally:
        sso_oidc.meta.events.unregister(event, short_circuit)
    return resolved["base_url"]


class _CallbackServer(HTTPServer):
    """
    The server on 127.0.0.1 that the browser comes back to with the authorization code, on a free port.

    It follows the AWS CLI's AuthCodeFetcher. Any local process, and maybe any web page, can reach it, so only a GET on
    the callback path with the expected ``state`` ends the wait. Every other request is rejected and the wait goes on.
    """

    def __init__(self) -> None:
        self.expected_state = ""
        self.deadline = monotonic() + _AUTH_CODE_TIMEOUT
        self.done = False
        self.code: Optional[str] = None
        self.error: Optional[str] = None
        super().__init__((_CALLBACK_HOST, 0), _CallbackHandler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # The default prints a traceback to stderr, e.g. when the browser disconnects before reading the page.
        LOG.debug("An OAuth callback request from %s failed", client_address, exc_info=True)

    def set_code(self, code: str) -> None:
        """Record the authorization code, which ends the wait."""
        self.code = code
        self.done = True

    def set_error(self, error: str, description: Optional[str]) -> None:
        """Record the error the authorization server sent back, which ends the wait."""
        self.error = f"{error} ({description})" if description else error
        self.done = True

    def wait_for_code(self, expected_state: str, deadline: float) -> str:
        """
        Handle requests until the browser comes back with the expected state, or the deadline passes.

        :param expected_state: The ``state`` sent in the authorize URL.
        :param deadline: When to give up, in :func:`time.monotonic` seconds.
        :return: The authorization code.
        :raise IHAWSException: If the authorization server sent an error, or the deadline passed.
        """
        self.expected_state = expected_state
        self.deadline = deadline
        while not self.done:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise IHAWSException(
                    f"The browser didn't complete the SSO login in {_AUTH_CODE_TIMEOUT} seconds. If you can't approve"
                    " it in a browser on this machine, retry with use_device_code=True."
                )
            self.timeout = min(_CALLBACK_REQUEST_TIMEOUT, remaining)
            self.handle_request()

        if self.error is not None:
            raise IHAWSException(f"The SSO login failed: {self.error}")
        return self.code


class _CallbackHandler(BaseHTTPRequestHandler):
    """
    Handles one request to the callback server.

    Each connection gets at most ``_CALLBACK_REQUEST_TIMEOUT`` seconds in total, and no more than the wait has left,
    as in the AWS CLI's ``_DeadlineOAuthCallbackHandler``. A per-read timeout alone would let a client that sends one
    byte at a time hold the connection, and the wait, indefinitely.
    """

    server: _CallbackServer

    def __init__(self, request: Any, client_address: Any, server: _CallbackServer) -> None:
        self._cut_off_lock = threading.Lock()
        self._finished = False
        self._cut_off = False
        self._cut_off_timer: Optional[threading.Timer] = None
        super().__init__(request, client_address, server)

    def setup(self) -> None:
        time_allowed = max(0.0, min(_CALLBACK_REQUEST_TIMEOUT, self.server.deadline - monotonic()))
        # StreamRequestHandler.setup() applies this to the socket.
        self.timeout = max(_MIN_READ_TIMEOUT, time_allowed)
        super().setup()
        self._cut_off_timer = threading.Timer(time_allowed, self._cut_off_connection)
        self._cut_off_timer.daemon = True
        self._cut_off_timer.start()

    def handle(self) -> None:
        try:
            super().handle()
        except OSError:
            # Reading from or writing to a connection that was cut off.
            if not self._cut_off:
                raise
        if self._cut_off:
            LOG.debug("Closed an OAuth callback connection that took too long")

    def finish(self) -> None:
        with self._cut_off_lock:
            self._finished = True
        if self._cut_off_timer is not None:
            self._cut_off_timer.cancel()
        super().finish()

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """Act on the browser's redirect, and reject everything else."""
        url = urlsplit(self.path)
        if url.path != _CALLBACK_PATH:
            self._send_text(404, "Not found.")
            return

        params = parse_qs(url.query)
        state = params.get("state", [None])[0]
        if state is None or not hmac.compare_digest(state.encode("utf-8"), self.server.expected_state.encode("utf-8")):
            self._send_text(
                400,
                "This request does not belong to the login in progress. Return to the terminal and use the URL it"
                " shows.",
            )
            return

        if "error" in params:
            self.server.set_error(params["error"][0], params.get("error_description", [None])[0])
            self._send_text(200, "The AWS SSO login failed. Return to the terminal for details.")
        elif "code" in params:
            self.server.set_code(params["code"][0])
            self._send_text(200, "The AWS SSO login is finished. You can close this window.")
        else:
            self._send_text(400, "The request has neither an authorization code nor an error.")

    def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
        # The default writes every request line to stderr, and the callback's request line holds the authorization
        # code.
        pass

    def _cut_off_connection(self) -> None:
        # Runs on the timer's thread. Shutting the socket down ends a read or write that is blocked on it.
        with self._cut_off_lock:
            if self._finished:
                return
            self._cut_off = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _send_text(self, status: int, text: str) -> None:
        LOG.debug("Answered an OAuth callback request with HTTP %d", status)
        body = f"{text}\n".encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# --- Device flow ---


def _device_code_login(login: _Login, reason: str, open_browser: bool) -> dict:
    """
    Log in with the device flow: the user opens a URL on any device and enters a code.

    :param reason: Why the device flow runs, for the log.
    :param open_browser: Also open the verification URL in the local browser.
    :return: The token to save.
    :raise IHAWSException: If the login can't start, or isn't approved in time.
    """
    LOG.info("Logging in with the device flow, because %s.", reason)
    # As the AWS CLI's SSOTokenFetcher: scopes, and no grant types.
    registration = _register_client(login)
    try:
        device_authorization = login.sso_oidc.start_device_authorization(
            clientId=registration["clientId"],
            clientSecret=registration["clientSecret"],
            startUrl=login.start_url,
        )
    except ClientError as err:
        raise IHAWSException(
            f"Failed to start SSO device authorization for profile '{login.profile_name}': "
            f"{_format_client_error(err)}. "
            f"Check your SSO configuration (sso_start_url: {login.start_url})"
        ) from err

    expires_in = device_authorization["expiresIn"]
    interval = device_authorization["interval"]
    LOG.info(
        "Verify user code %s at %s within %d seconds.",
        device_authorization["userCode"],
        device_authorization["verificationUri"],
        expires_in,
    )
    print(
        "To approve the AWS SSO login, open this URL in a browser on any device:\n\n"
        f"    {device_authorization['verificationUri']}\n\n"
        f"and enter the code:\n\n    {device_authorization['userCode']}\n\n"
        f"Or open this URL, which fills in the code:\n\n    {device_authorization['verificationUriComplete']}\n",
        file=sys.stderr,
    )
    if open_browser:
        webbrowser.open(device_authorization["verificationUriComplete"], autoraise=True)

    for _ in range(1, expires_in // interval + 1):
        sleep(interval)
        try:
            response = login.sso_oidc.create_token(
                grantType=_DEVICE_CODE_GRANT_TYPE,
                deviceCode=device_authorization["deviceCode"],
                clientId=registration["clientId"],
                clientSecret=registration["clientSecret"],
            )
        except login.sso_oidc.exceptions.AuthorizationPendingException:
            continue
        return _make_token(login, registration, response)

    raise IHAWSException(f"The verification code isn't confirmed by user in {expires_in} seconds")


# --- Shared by both flows ---


def _register_client(login: _Login, **registration: Any) -> dict:
    """
    Register a new public OIDC client with the sso-session's scopes. A login never reuses a registration.

    :param registration: More register_client parameters, e.g. the PKCE flow's grant types.
    :return: The register_client response.
    :raise IHAWSException: If the registration fails.
    """
    try:
        return login.sso_oidc.register_client(
            clientName=_CLIENT_NAME, clientType="public", scopes=login.scopes, **registration
        )
    except ClientError as err:
        raise IHAWSException(
            f"Failed to register SSO client for profile '{login.profile_name}': {_format_client_error(err)}"
        ) from err


def _make_token(login: _Login, registration: dict, response: dict) -> dict:
    """
    Build the token to save, with the fields botocore reads, as the AWS CLI builds it.

    :param registration: The register_client response.
    :param response: The create_token response.
    :return: The token. Its two dates are UTC datetimes; :func:`_dump_sso_token` writes them.
    """
    token = {
        "startUrl": login.start_url,
        "region": login.sso_region,
        "accessToken": response["accessToken"],
        "expiresAt": datetime.now(timezone.utc) + timedelta(seconds=response["expiresIn"]),
        # The registration goes with the token, so botocore can refresh it.
        "clientId": registration["clientId"],
        "clientSecret": registration["clientSecret"],
        # register_client gives epoch seconds.
        "registrationExpiresAt": datetime.fromtimestamp(registration["clientSecretExpiresAt"], timezone.utc),
    }
    if "refreshToken" in response:
        token["refreshToken"] = response["refreshToken"]
    return token


def _dump_sso_token(token: dict) -> str:
    """
    Serialise a token as botocore's ``_sso_json_dumps`` does, with dates as UTC ``YYYY-MM-DDTHH:MM:SSZ``.

    botocore's function is private, so ih-aws doesn't import it; a test compares the two.
    """
    return dumps(token, default=_utc_timestamp)


def _utc_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime(_UTC_FORMAT)
    # The message names the type only: the value might be a secret.
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _format_client_error(err: ClientError) -> str:
    """Extract error code and message from a ClientError."""
    error_info = err.response.get("Error", {})
    code = error_info.get("Code", "Unknown")
    message = error_info.get("Message") or "No details provided"
    return f"{code} - {message}"


def _get_sso_oidc_client(sso_region: str) -> Any:
    """An sso-oidc client. Its calls are unsigned, so it needs no AWS credentials."""
    return Session().client("sso-oidc", region_name=sso_region, config=Config(signature_version=UNSIGNED))


def _sso_token_cache_dir() -> str:
    """``~/.aws/sso/cache``, where botocore and the AWS CLI keep SSO tokens."""
    return os.path.join(os.path.expanduser("~"), ".aws", "sso", "cache")


def _make_private_dirs(path: str) -> None:
    """
    Create a directory and any missing parents with mode 0700. Directories that exist keep their mode.

    :raise OSError: If a directory can't be created.
    """
    missing = []
    current = path
    while not os.path.isdir(current):
        missing.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            # Someone else just created it, or it isn't a directory; either way, leave its mode alone.
            continue
        # mkdir applies the umask.
        os.chmod(directory, 0o700)
