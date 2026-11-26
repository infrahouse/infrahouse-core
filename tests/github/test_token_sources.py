"""
Tests for GitHub App installation tokens: the JWT signers and the token sources (SEC-46).

The App source runs against a local HTTP server that answers the GitHub App endpoints, so the tests see the JWT and
the body of every request the App sends. KMS is a fake client that signs with an RSA key generated for the test.
Nothing here calls GitHub or AWS.
"""

import base64
import inspect
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Optional
from unittest import mock
from urllib.parse import urlparse

import jwt
import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from github import GithubException
from github.Consts import DEFAULT_JWT_ISSUED_AT, MAX_JWT_EXPIRY
from requests import HTTPError

from infrahouse_core import github as ih_github
from infrahouse_core.aws import secretsmanager
from infrahouse_core.github import (
    GitHubAppTokenSource,
    GitHubTokenSource,
    JWTSigner,
    KMSSigner,
    PEMSecretSigner,
    get_tmp_token,
)

# The new code must not call deprecated PyGithub APIs, such as GithubIntegration.create_jwt() or the positional
# GithubIntegration(app_id, private_key) form.
pytestmark = pytest.mark.filterwarnings("error::DeprecationWarning")

APP_ID = 123456
ORG = "test-org"
INSTALLATION_ID = 42
TOKEN = "ghs_TestInstallationToken0123456789"
REGION = "us-west-2"
ROLE_ARN = "arn:aws:iam::123456789012:role/github-token-reader"
KEY_ARN = "arn:aws:kms:us-west-2:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab"
PEM_SECRET = "arn:aws:secretsmanager:us-west-2:123456789012:secret:github-app-pem-AbCdEf"
TOKEN_PATH = f"/app/installations/{INSTALLATION_ID}/access_tokens"
# The three requests the App source sends as the App, in order: list installations, look up the account of the
# installation, exchange the JWT for an installation token.
APP_REQUESTS = [
    ("GET", "/app/installations"),
    ("GET", f"/app/installations/{INSTALLATION_ID}"),
    ("POST", TOKEN_PATH),
]


# --- Keys and fake AWS clients ---


@dataclass(frozen=True)
class AppKey:
    """A GitHub App private key generated for the tests."""

    private_key: rsa.RSAPrivateKey
    pem: str

    @property
    def public_key(self) -> rsa.RSAPublicKey:
        return self.private_key.public_key()


@pytest.fixture(scope="module")
def app_key() -> AppKey:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # GitHub hands out the App key as PKCS#1 PEM ("BEGIN RSA PRIVATE KEY").
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return AppKey(private_key, pem)


class FakeKMS:
    """
    A KMS client whose ``sign()`` signs as ``kms:Sign`` does with ``RSASSA_PKCS1_V1_5_SHA_256`` and
    ``MessageType=RAW``: it hashes ``Message`` with SHA-256 and signs with PKCS#1 v1.5.

    Every call's arguments are recorded in ``calls``. With ``error_code``, ``sign()`` raises a ``ClientError`` with that
    code instead.
    """

    def __init__(self, private_key: rsa.RSAPrivateKey, error_code: Optional[str] = None):
        self._private_key = private_key
        self._error_code = error_code
        self.calls: List[Dict[str, Any]] = []

    def sign(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self._error_code:
            raise ClientError({"Error": {"Code": self._error_code, "Message": "fake KMS error"}}, "Sign")
        signature = self._private_key.sign(kwargs["Message"], padding.PKCS1v15(), hashes.SHA256())
        return {"KeyId": kwargs["KeyId"], "Signature": signature, "SigningAlgorithm": kwargs["SigningAlgorithm"]}


@pytest.fixture
def fake_kms(app_key) -> FakeKMS:
    return FakeKMS(app_key.private_key)


@pytest.fixture
def kms_get_client(fake_kms) -> Iterator[mock.Mock]:
    """Patch the helper that ``KMSSigner`` creates its boto3 client with; the patch returns ``fake_kms``."""
    with mock.patch.object(ih_github, "get_client", return_value=fake_kms) as get_client:
        yield get_client


@pytest.fixture
def secrets_client(app_key) -> mock.Mock:
    """A Secrets Manager client that returns the App's PEM."""
    client = mock.Mock()
    client.get_secret_value.return_value = {"SecretString": app_key.pem}
    return client


@pytest.fixture
def secrets_get_client(secrets_client) -> Iterator[mock.Mock]:
    """Patch the helper that ``Secret`` creates its boto3 client with; the patch returns ``secrets_client``."""
    with mock.patch.object(secretsmanager, "get_client", return_value=secrets_client) as get_client:
        yield get_client


@pytest.fixture(params=["pem", "kms"])
def signer(request, secrets_get_client, kms_get_client) -> JWTSigner:
    """Each of the two signers, backed by the same App key."""
    if request.param == "pem":
        return PEMSecretSigner(PEM_SECRET, region=REGION)
    return KMSSigner(KEY_ARN, region=REGION)


# --- A local server that answers the GitHub App endpoints ---


@dataclass
class RecordedRequest:
    """One request the fake GitHub received. Header names are lower case."""

    method: str
    path: str
    headers: Dict[str, str]
    body: Optional[Any]

    @property
    def jwt(self) -> str:
        scheme, _, credentials = self.headers.get("authorization", "").partition(" ")
        assert scheme == "Bearer", f"{self.method} {self.path} wasn't authenticated with a JWT"
        return credentials


def _installation(installation_id: int, target_type: str, login: str) -> dict:
    return {"id": installation_id, "target_type": target_type, "account": {"login": login}}


_INSTALLATION_PATH = re.compile(r"^/app/installations/(\d+)$")
_ACCESS_TOKENS_PATH = re.compile(r"^/app/installations/(\d+)/access_tokens$")


class FakeGitHubApp(ThreadingHTTPServer):
    """
    A local HTTP server that answers the GitHub App endpoints that the token source calls.

    ``GET /app/installations`` lists ``installations``, and ``GET /app/installations/{id}`` returns one of them, or
    ``org_lookup_status`` if that isn't 200. ``POST /app/installations/{id}/access_tokens`` answers with
    ``token_status`` and ``token_body``. Every request is recorded in ``requests``.
    """

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.installations: List[dict] = [_installation(INSTALLATION_ID, "Organization", ORG)]
        self.org_lookup_status = 200
        self.token_status = 201
        self.token_body: dict = {"token": TOKEN, "expires_at": "2026-11-26T11:00:00Z"}
        self.requests: List[RecordedRequest] = []
        self.lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    @property
    def calls(self) -> List[tuple]:
        return [(request.method, request.path) for request in self.requests]

    def find_installation(self, installation_id: int) -> Optional[dict]:
        return next((i for i in self.installations if i["id"] == installation_id), None)


class _Handler(BaseHTTPRequestHandler):
    server: FakeGitHubApp

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        path = self._record()
        match = _INSTALLATION_PATH.match(path)
        if path == "/app/installations":
            self._respond(200, self.server.installations)
        elif match and self.server.find_installation(int(match.group(1))):
            if self.server.org_lookup_status == 200:
                self._respond(200, self.server.find_installation(int(match.group(1))))
            else:
                self._respond(self.server.org_lookup_status, {"message": "Not Found"})
        else:
            self._respond(404, {"message": "Not Found"})

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        path = self._record()
        if _ACCESS_TOKENS_PATH.match(path):
            self._respond(self.server.token_status, self.server.token_body)
        else:
            self._respond(404, {"message": "Not Found"})

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Keep the server quiet."""

    def _record(self) -> str:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        request = RecordedRequest(
            method=self.command,
            path=urlparse(self.path).path,
            headers={name.lower(): value for name, value in self.headers.items()},
            body=json.loads(raw) if raw else None,
        )
        with self.server.lock:
            self.server.requests.append(request)
        return request.path

    def _respond(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def fake_github() -> Iterator[FakeGitHubApp]:
    """Start a fake GitHub and point the module at it, for both PyGithub and the module's own requests."""
    server = FakeGitHubApp()
    # A short poll interval keeps shutdown() fast; the default 0.5 s would add half a second to every test.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        with mock.patch.object(ih_github, "_GITHUB_API_URL", server.base_url):
            yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


# --- Helpers ---


def _claims(token: str, app_key: AppKey) -> dict:
    """Verify ``token`` against the App's public key, as GitHub does, and return its claims."""
    return jwt.decode(token, app_key.public_key, algorithms=["RS256"])


def _b64decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _payload() -> dict:
    """A JWT payload as PyGithub's AppAuth builds it."""
    now = int(time.time())
    return {"iat": now + DEFAULT_JWT_ISSUED_AT, "exp": now + MAX_JWT_EXPIRY, "iss": str(APP_ID)}


# --- KMSSigner ---


def test_kms_signer_calls_sign_with_raw_message_and_rs256(kms_get_client, fake_kms):
    token = KMSSigner(KEY_ARN, region=REGION).sign(_payload())

    signing_input = token.rsplit(".", 1)[0].encode()
    assert fake_kms.calls == [
        {
            "KeyId": KEY_ARN,
            "Message": signing_input,
            "MessageType": "RAW",
            "SigningAlgorithm": "RSASSA_PKCS1_V1_5_SHA_256",
        }
    ]


def test_kms_signer_jwt_verifies_with_app_public_key(kms_get_client, app_key):
    payload = _payload()

    token = KMSSigner(KEY_ARN, region=REGION).sign(payload)

    assert _claims(token, app_key) == payload


def test_kms_signer_jwt_does_not_verify_with_another_key(kms_get_client):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    token = KMSSigner(KEY_ARN, region=REGION).sign(_payload())

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, other_key.public_key(), algorithms=["RS256"])


def test_kms_signer_header_is_rs256_jwt(kms_get_client):
    token = KMSSigner(KEY_ARN, region=REGION).sign(_payload())

    assert jwt.get_unverified_header(token) == {"alg": "RS256", "typ": "JWT"}
    # Compact JSON, keys in this order: the same bytes PyJWT writes.
    assert _b64decode(token.split(".")[0]) == b'{"alg":"RS256","typ":"JWT"}'


def test_kms_signer_payload_is_compact_json(kms_get_client):
    payload = {"iat": 1700000000, "exp": 1700000600, "iss": str(APP_ID)}

    token = KMSSigner(KEY_ARN, region=REGION).sign(payload)

    assert _b64decode(token.split(".")[1]) == b'{"iat":1700000000,"exp":1700000600,"iss":"123456"}'


def test_kms_signer_base64url_without_padding(kms_get_client):
    token = KMSSigner(KEY_ARN, region=REGION).sign(_payload())

    segments = token.split(".")
    assert len(segments) == 3
    for segment in segments:
        assert re.fullmatch(r"[A-Za-z0-9_-]+", segment), segment


def test_kms_signer_jwt_identical_to_pem_signer(kms_get_client, secrets_get_client):
    """PKCS#1 v1.5 is deterministic: with the same key and payload, both signers must produce the same JWT."""
    payload = _payload()

    kms_token = KMSSigner(KEY_ARN, region=REGION).sign(payload)
    pem_token = PEMSecretSigner(PEM_SECRET, region=REGION).sign(payload)

    assert kms_token == pem_token


@pytest.mark.parametrize(
    "key_id",
    [
        pytest.param("1234abcd-12ab-34cd-56ef-1234567890ab", id="key-id"),
        pytest.param(KEY_ARN, id="key-arn"),
        pytest.param("alias/github-app", id="alias-name"),
        pytest.param("arn:aws:kms:us-west-2:123456789012:alias/github-app", id="alias-arn"),
    ],
)
def test_kms_signer_passes_key_id_through(kms_get_client, fake_kms, key_id):
    KMSSigner(key_id, region=REGION).sign(_payload())

    assert fake_kms.calls[0]["KeyId"] == key_id


def test_kms_signer_creates_client_lazily_with_region_and_role(kms_get_client):
    signer = KMSSigner(KEY_ARN, region=REGION, role_arn=ROLE_ARN)
    kms_get_client.assert_not_called()

    signer.sign(_payload())
    signer.sign(_payload())

    kms_get_client.assert_called_once_with("kms", role_arn=ROLE_ARN, region=REGION)


def test_kms_signer_creates_client_from_session(kms_get_client, fake_kms):
    session = mock.Mock()
    session.client.return_value = fake_kms
    signer = KMSSigner(KEY_ARN, region=REGION, session=session)

    signer.sign(_payload())
    signer.sign(_payload())

    session.client.assert_called_once_with("kms", region_name=REGION)
    kms_get_client.assert_not_called()


@pytest.mark.parametrize("error_code", ["AccessDeniedException", "DisabledException", "KMSInvalidStateException"])
def test_kms_signer_client_error_propagates(app_key, error_code):
    kms = FakeKMS(app_key.private_key, error_code=error_code)
    with mock.patch.object(ih_github, "get_client", return_value=kms):
        with pytest.raises(ClientError) as err:
            KMSSigner(KEY_ARN, region=REGION).sign(_payload())

    assert err.value.response["Error"]["Code"] == error_code


# --- PEMSecretSigner ---


def test_pem_signer_signs_like_pyjwt(secrets_get_client, app_key):
    payload = _payload()

    token = PEMSecretSigner(PEM_SECRET, region=REGION).sign(payload)

    assert token == jwt.encode(payload, app_key.pem, algorithm="RS256")
    assert _claims(token, app_key) == payload


def test_pem_signer_reads_secret_once_lazily(secrets_get_client, secrets_client):
    signer = PEMSecretSigner(PEM_SECRET, region=REGION, role_arn=ROLE_ARN)
    secrets_get_client.assert_not_called()

    signer.sign(_payload())
    signer.sign(_payload())

    secrets_get_client.assert_called_once_with("secretsmanager", role_arn=ROLE_ARN, region=REGION)
    secrets_client.get_secret_value.assert_called_once_with(SecretId=PEM_SECRET)


# --- GitHubAppTokenSource ---


def test_token_source_is_the_interface():
    assert issubclass(GitHubAppTokenSource, GitHubTokenSource)
    with pytest.raises(TypeError):
        GitHubTokenSource()  # pylint: disable=abstract-class-instantiated


def test_token_source_interface_needs_only_installation_token():
    """A source that gets tokens elsewhere, such as from a broker, implements one method and nothing else."""

    class StaticTokenSource(GitHubTokenSource):
        def installation_token(self, github_org_name: str, permissions: Optional[dict] = None) -> str:
            return f"token for {github_org_name} with {permissions}"

    source: GitHubTokenSource = StaticTokenSource()

    assert (
        source.installation_token(ORG, permissions={"metadata": "read"})
        == "token for test-org with {'metadata': 'read'}"
    )


def test_app_source_returns_installation_token(fake_github, signer):
    assert GitHubAppTokenSource(APP_ID, signer).installation_token(ORG) == TOKEN
    assert fake_github.calls == APP_REQUESTS


def test_app_source_signs_every_app_request(fake_github, signer, app_key):
    """Every request made as the App carries a JWT from the signer that verifies against the App's public key."""
    before = int(time.time())

    GitHubAppTokenSource(APP_ID, signer).installation_token(ORG)

    after = int(time.time())
    assert fake_github.calls == APP_REQUESTS
    for request in fake_github.requests:
        claims = _claims(request.jwt, app_key)
        assert claims["iss"] == str(APP_ID), request.path
        # GitHub rejects a JWT whose exp is more than 10 minutes (MAX_JWT_EXPIRY) after the time it was made.
        assert before + MAX_JWT_EXPIRY <= claims["exp"] <= after + MAX_JWT_EXPIRY, request.path
        # PyGithub sets iat 60 seconds in the past against clock drift, as GitHub's docs recommend.
        assert before + DEFAULT_JWT_ISSUED_AT <= claims["iat"] <= after + DEFAULT_JWT_ISSUED_AT, request.path


def test_app_source_kms_and_pem_send_the_same_jwt(fake_github, secrets_get_client, kms_get_client, app_key):
    """Both signers send a JWT that verifies against the same public key, with the same claims, on every request."""
    sources = [
        GitHubAppTokenSource(APP_ID, PEMSecretSigner(PEM_SECRET, region=REGION)),
        GitHubAppTokenSource(APP_ID, KMSSigner(KEY_ARN, region=REGION)),
    ]

    for source in sources:
        assert source.installation_token(ORG) == TOKEN

    pem_requests, kms_requests = fake_github.requests[:3], fake_github.requests[3:]
    assert [(r.method, r.path) for r in pem_requests] == APP_REQUESTS
    assert [(r.method, r.path) for r in kms_requests] == APP_REQUESTS
    for pem_request, kms_request in zip(pem_requests, kms_requests):
        assert _claims(pem_request.jwt, app_key)["iss"] == _claims(kms_request.jwt, app_key)["iss"] == str(APP_ID)
        assert jwt.get_unverified_header(pem_request.jwt) == jwt.get_unverified_header(kms_request.jwt)


def test_app_source_sends_permissions_unchanged(fake_github, signer):
    permissions = {"organization_self_hosted_runners": "write", "metadata": "read"}

    GitHubAppTokenSource(APP_ID, signer).installation_token(ORG, permissions=permissions)

    token_request = fake_github.requests[-1]
    assert (token_request.method, token_request.path) == ("POST", TOKEN_PATH)
    assert token_request.body == {"permissions": permissions}


def test_app_source_without_permissions_requests_none(fake_github, signer):
    """
    Without ``permissions``, no permission is requested, and GitHub grants all the App's permissions.

    PyGithub sends an empty map in that case. ``get_tmp_token`` has always sent the same body.
    """
    GitHubAppTokenSource(APP_ID, signer).installation_token(ORG)

    token_request = fake_github.requests[-1]
    assert (token_request.method, token_request.path) == ("POST", TOKEN_PATH)
    assert token_request.body == {"permissions": {}}


def test_app_source_finds_installation_by_org_name(fake_github, signer):
    """User installations are skipped without a lookup; the organization is matched by its login."""
    fake_github.installations = [
        _installation(7, "User", ORG),
        _installation(8, "Organization", "another-org"),
        _installation(INSTALLATION_ID, "Organization", ORG),
    ]

    assert GitHubAppTokenSource(APP_ID, signer).installation_token(ORG) == TOKEN
    assert fake_github.calls == [
        ("GET", "/app/installations"),
        ("GET", "/app/installations/8"),
        ("GET", f"/app/installations/{INSTALLATION_ID}"),
        ("POST", TOKEN_PATH),
    ]


def test_app_source_no_installation_in_org(fake_github, signer):
    fake_github.installations = [_installation(7, "User", ORG), _installation(8, "Organization", "another-org")]

    with pytest.raises(RuntimeError, match=f"^Could not find installation of {APP_ID} in organization {ORG}$"):
        GitHubAppTokenSource(APP_ID, signer).installation_token(ORG)

    assert ("POST", TOKEN_PATH) not in fake_github.calls


def test_app_source_kms_error_reaches_caller(fake_github, app_key):
    kms = FakeKMS(app_key.private_key, error_code="AccessDeniedException")
    with mock.patch.object(ih_github, "get_client", return_value=kms):
        with pytest.raises(ClientError) as err:
            GitHubAppTokenSource(APP_ID, KMSSigner(KEY_ARN, region=REGION)).installation_token(ORG)

    assert err.value.response["Error"]["Code"] == "AccessDeniedException"
    # The JWT is signed before the first request is sent, so nothing reached GitHub.
    assert fake_github.requests == []


def test_app_source_token_exchange_error_reaches_caller(fake_github, signer):
    fake_github.token_status = 422
    fake_github.token_body = {"message": "The permissions requested are not granted to this installation."}

    with pytest.raises(GithubException) as err:
        GitHubAppTokenSource(APP_ID, signer).installation_token(
            ORG, permissions={"organization_self_hosted_runners": "write"}
        )

    assert err.value.status == 422
    assert "422" in str(err.value)


def test_app_source_org_lookup_error_reaches_caller(fake_github, signer):
    fake_github.org_lookup_status = 404

    with pytest.raises(HTTPError) as err:
        GitHubAppTokenSource(APP_ID, signer).installation_token(ORG)

    assert err.value.response.status_code == 404
    assert ("POST", TOKEN_PATH) not in fake_github.calls


def test_kms_client_created_once_for_two_tokens(fake_github, kms_get_client, fake_kms):
    source = GitHubAppTokenSource(APP_ID, KMSSigner(KEY_ARN, region=REGION, role_arn=ROLE_ARN))

    assert source.installation_token(ORG) == TOKEN
    assert source.installation_token(ORG) == TOKEN

    kms_get_client.assert_called_once_with("kms", role_arn=ROLE_ARN, region=REGION)
    # One signature for every request made as the App.
    assert len(fake_kms.calls) == 2 * len(APP_REQUESTS)


def test_no_key_jwt_or_token_in_logs(fake_github, signer, app_key, caplog):
    caplog.set_level(logging.DEBUG, logger="infrahouse_core")

    token = GitHubAppTokenSource(APP_ID, signer).installation_token(ORG)

    jwts = [request.jwt for request in fake_github.requests]
    assert jwts
    for secret in [token, app_key.pem, *jwts, *(j.rsplit(".", 1)[1] for j in jwts)]:
        assert secret not in caplog.text


# --- get_tmp_token ---


def test_get_tmp_token_signature_unchanged():
    assert str(inspect.signature(get_tmp_token)) == (
        "(gh_app_id: int, pem_key_secret: str, github_org_name: str, region: str = None, role_arn: str = None) -> str"
    )


def test_get_tmp_token_reads_pem_from_given_secret(fake_github, secrets_get_client, secrets_client, app_key):
    token = get_tmp_token(APP_ID, PEM_SECRET, ORG, region=REGION, role_arn=ROLE_ARN)

    assert token == TOKEN
    secrets_get_client.assert_called_once_with("secretsmanager", role_arn=ROLE_ARN, region=REGION)
    secrets_client.get_secret_value.assert_called_once_with(SecretId=PEM_SECRET)
    assert fake_github.calls == APP_REQUESTS
    for request in fake_github.requests:
        assert _claims(request.jwt, app_key)["iss"] == str(APP_ID)
    assert fake_github.requests[-1].body == {"permissions": {}}


def test_get_tmp_token_no_installation_in_org(fake_github, secrets_get_client):
    fake_github.installations = []

    with pytest.raises(RuntimeError, match=f"^Could not find installation of {APP_ID} in organization {ORG}$"):
        get_tmp_token(APP_ID, PEM_SECRET, ORG)
