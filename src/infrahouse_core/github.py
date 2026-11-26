"""
GitHub Actions

Calls to the GitHub REST API made by this module go through one shared
:class:`requests.Session` that retries transient failures: dropped
connections, connection errors, read timeouts, and responses with status
429, 500, 502, 503 or 504. Each call is tried up to six times, with
backoff sleeps of 0, 1, 2, 4 and 8 seconds between attempts, or as long
as GitHub's ``Retry-After`` header says. urllib3 logs each retry at
WARNING on the ``urllib3`` logger. When the retries run out, the caller
gets the same exception as without retries: :class:`requests.HTTPError`
for an HTTP error status, :class:`requests.ReadTimeout` for a read
timeout, and :class:`requests.ConnectionError` for other network errors.
Two calls don't use that session: :class:`GitHubAppTokenSource` lists the
App's installations and exchanges the JWT for a token through PyGithub,
which has its own connection.

GitHub App installation tokens come from a :class:`GitHubTokenSource`.
:class:`GitHubAppTokenSource` mints them as the App, with the App JWT
signed by a :class:`JWTSigner`: :class:`KMSSigner` signs with ``kms:Sign``
and a key that never leaves KMS, :class:`PEMSecretSigner` signs with a
PEM key read from AWS Secrets Manager. :func:`get_tmp_token` is the
PEM-signed source behind the original function signature.
"""

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cache
from logging import getLogger
from typing import Iterator, List, Optional, Union

from cached_property import cached_property_with_ttl
from github import GithubIntegration
from github.Auth import AppAuth
from github.Consts import DEFAULT_JWT_ALGORITHM, MAX_JWT_EXPIRY
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, ReadTimeout, Response, Session
from requests.adapters import HTTPAdapter
from urllib3.exceptions import MaxRetryError, ReadTimeoutError
from urllib3.util import Retry

from infrahouse_core.aws import get_client
from infrahouse_core.aws.secretsmanager import Secret

LOG = getLogger(__name__)

# Private so that it isn't API. Tests point it at a local plain-HTTP server; see _get_session().
_GITHUB_API_URL = "https://api.github.com"

# Retry policy for the GitHub REST API calls in this module. See _get_session().
# With urllib3 2.x, a backoff factor of 0.5 sleeps 0, 1, 2, 4 and 8 seconds between the six attempts.
_RETRY_TOTAL = 5
_RETRY_BACKOFF_FACTOR = 0.5
_RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)
# POST is retried on purpose, although it isn't idempotent. The only POST in this module requests a
# runner registration token. Retrying it after a lost response at worst creates an extra short-lived
# token, and GitHub expires unused tokens. Any POST added to this module later is retried too, so make
# sure repeating it is harmless.
_RETRY_ALLOWED_METHODS = frozenset({"GET", "DELETE", "POST"})

# The JOSE header of the App JWTs that KMSSigner signs. GitHub accepts only RS256.
_JWT_HEADER = {"alg": "RS256", "typ": "JWT"}
# The kms:Sign algorithm that makes an RS256 signature: RSASSA-PKCS1-v1_5 with SHA-256. With MessageType RAW,
# KMS hashes the message itself.
_KMS_SIGNING_ALGORITHM = "RSASSA_PKCS1_V1_5_SHA_256"


@dataclass
class GitHubAuth:
    """
    Authentication information for GitHub API access.

    This class holds the necessary credentials to authenticate with the GitHub API.
    It is used by other classes in this module to make authenticated API calls.

    .. warning::
        Tokens should be stored securely (e.g., AWS Secrets Manager).
        Never log or print the token value.
        Rotate tokens regularly following your organization's security policy.

    :param token: GitHub Personal Access Token or GitHub App token for authentication.
        Retrieve from secure storage, never hardcode.
    :type token: str
    :param org: GitHub organization name where the runners are registered
    :type org: str
    """

    token: str
    org: str


class GitHubActionsRunner:
    """
    Represents a GitHub Actions self-hosted runner instance.

    Provides access to runner metadata such as status, labels, and instance ID,
    fetched dynamically via the GitHub API.
    """

    def __init__(self, runner_id: int, github: GitHubAuth, runner_data: Optional[dict] = None):
        """
        Initialize the GitHubActionsRunner.

        :param runner_id: The numeric ID of the GitHub runner.
        :type runner_id: int
        :param github: Authentication object containing token and org name.
        :type github: GitHubAuth
        :param runner_data: Optional runner data to avoid an extra API call.
        :type runner_data: dict
        """
        self._runner_id = runner_id
        self._github = github
        self.__runner_data = runner_data

    @property
    def runner_id(self) -> int:
        """
        Return the runner ID.

        :return: The ID of the GitHub runner.
        :rtype: int
        """
        return self._runner_id

    @property
    def busy(self) -> bool:
        """
        Indicates whether the runner is currently executing a job.

        :return: True if the runner is busy, False otherwise.
        :rtype: bool
        """
        return self._runner_data["busy"]

    @property
    def instance_id(self) -> str:
        """
        Extract the EC2 instance ID from the runner's labels.

        :return: The instance ID if found, otherwise None.
        :rtype: str or None
        """
        return next((label.split(":", 1)[1] for label in self.labels if label.startswith("instance_id:")), None)

    @property
    def labels(self) -> List[str]:
        """
        List all labels assigned to the runner.

        :return: A list of label names.
        :rtype: list[str]
        """
        return [x["name"] for x in self._runner_data["labels"]]

    @property
    def name(self) -> str:
        """
        Return the name of the runner.

        :return: Runner name.
        :rtype: str
        """
        return self._runner_data["name"]

    @property
    def os(self) -> str:
        """
        Return the operating system of the runner.

        :return: OS name (e.g., "linux", "windows").
        :rtype: str
        """
        return self._runner_data["os"]

    @property
    def status(self) -> str:
        """
        Return the runner's status.

        :return: Status string (e.g., "online", "offline").
        :rtype: str
        """
        return self._runner_data["status"]

    @property
    def _github_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._github.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @cached_property_with_ttl(ttl=10)
    def _runner_data(self) -> dict:
        """
        Retrieve runner metadata from the GitHub API.

        :return: JSON response with runner details.
        :rtype: dict
        """
        if self.__runner_data is None:
            try:
                response = _request(
                    "GET",
                    f"{_GITHUB_API_URL}/orgs/{self._github.org}/actions/runners/{self._runner_id}",
                    headers=self._github_headers,
                    timeout=5,
                )
                response.raise_for_status()
                self.__runner_data = response.json()
            except HTTPError as err:
                LOG.error("Failed to fetch runner: %s", err)
                raise

        return self.__runner_data


class GitHubActions:
    """
    The GitHubActions class manages self-hosted GitHub Action runners for an organization.

    :param github: GitHub authentication information (token and org).
    :type github: GitHubAuth
    :param region: AWS region for Secrets Manager operations.
    :type region: str
    :param role_arn: IAM role ARN to assume for cross-account access.
    :type role_arn: str

    Example::

        auth = GitHubAuth(token="ghp_...", org="my-org")
        gha = GitHubActions(auth, region="us-east-1")

        # Store a registration token in Secrets Manager
        gha.ensure_registration_token("my-runner-token")

        # Iterate over runners (lazy — one API page at a time)
        for runner in gha.runners:
            print(runner.name, runner.status)

        runner = gha.find_runner_by_label("instance_id:i-abc123")
        if runner:
            gha.deregister_runner(runner)

        # Clean up the token
        gha.ensure_registration_token("my-runner-token", present=False)

    .. note::
        ``runners`` and ``find_runners_by_label()`` return iterators, not lists.
        They fetch subsequent GitHub API pages only as the iterator advances, so
        memory usage stays bounded to one page (~100 runners) regardless of
        organization size. This is important in memory-constrained environments
        such as 128 MB AWS Lambda functions. Callers that need a materialized
        collection should wrap the result with ``list()``.
    """

    def __init__(self, github: GitHubAuth, region: str = None, role_arn: str = None):
        """
        Initialize the GitHubActions manager.
        """
        self._github = github
        self._region = region
        self._role_arn = role_arn

    @property
    def registration_token(self) -> str:
        """
        Request a registration token from GitHub for registering a new runner.

        :return: A registration token string.
        :rtype: str
        """
        response = _request(
            "POST",
            f"{_GITHUB_API_URL}/orgs/{self._github.org}/actions/runners/registration-token",
            headers=self._github_headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["token"]

    @property
    def runners(self) -> Iterator[GitHubActionsRunner]:
        """
        Iterate over all self-hosted runners for the organization.

        Yields runners one at a time, fetching subsequent API pages only as
        the iterator advances. Keeps memory usage bounded to one page when
        running in memory-constrained environments (e.g. Lambda).

        Each access to this property returns a **new independent generator**.
        Iterating it consumes the generator; a second ``for r in gha.runners``
        loop will replay the GitHub API calls from scratch. If you need to
        iterate the same set of runners more than once, wrap the first access
        with ``list()`` to materialize the results::

            snapshot = list(gha.runners)
            busy = [r for r in snapshot if r.busy]
            idle = [r for r in snapshot if not r.busy]

        :return: An iterator of GitHubActionsRunner objects.
        :rtype: Iterator[GitHubActionsRunner]
        """
        yield from (GitHubActionsRunner(r["id"], self._github, runner_data=r) for r in self._get_github_runners())

    def deregister_runner(self, runner: GitHubActionsRunner):
        """
        De-register a self-hosted runner from the GitHub organization.

        Issues ``DELETE /orgs/{org}/actions/runners/{runner_id}`` and raises
        if GitHub returns a non-2xx response. The caller is responsible for
        stopping the runner process and terminating its host; this method
        only removes GitHub's record of the runner.

        Transient failures are retried (see the module docstring). If GitHub
        removed the runner but the response was lost, the retry gets 404, so
        this method raises ``HTTPError`` even though the runner is gone.

        :param runner: The runner to de-register.
        :type runner: GitHubActionsRunner
        :raises requests.HTTPError: If the GitHub API returns a non-2xx status
            (for example, 404 if the runner was already removed).
        """
        response = _request(
            "DELETE",
            f"{_GITHUB_API_URL}/orgs/{self._github.org}/actions/runners/{runner.runner_id}",
            headers=self._github_headers,
            timeout=30,
        )
        response.raise_for_status()

    def ensure_registration_token(self, registration_token_secret: str, present=True):
        """
        Ensure a registration token is present (by default) or absent in AWS Secrets Manager.
        If the argument `present` is true, and the registration token is secret does not exist,
        it will be created.
        If the argument `present` is false, and the registration token is secret exist,
        it will be deleted.

        :param registration_token_secret: The name of the secret to store the token.
        :type registration_token_secret: str
        :param present: Whether the registration token should be present or not.
        :type present: bool
        """
        if present:
            self._ensure_present_secret(registration_token_secret)
        else:
            self._ensure_absent_secret(registration_token_secret)

    def find_runner_by_label(self, label: str) -> Optional[GitHubActionsRunner]:
        """
        Find the first runner that has the specified label.

        :param label: The label to search for.
        :type label: str
        :return: The first runner matching the label, or None if not found.
        :rtype: GitHubActionsRunner or None
        """
        return next((runner for runner in self.runners if label in runner.labels), None)

    def find_runners_by_label(self, label: str) -> Iterator[GitHubActionsRunner]:
        """
        Yield all runners that have the specified label.

        Iterates lazily over the organization's runners, fetching subsequent
        API pages only as the caller advances the iterator. Callers that need
        a materialized collection should wrap the result with ``list()``.

        :param label: The label to search for.
        :type label: str
        :return: An iterator of GitHubActionsRunner objects that match the label.
        :rtype: Iterator[GitHubActionsRunner]
        """
        yield from (runner for runner in self.runners if label in runner.labels)

    @property
    def _github_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._github.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get_github_runners(self) -> Iterator[dict]:
        """
        Yield raw runner metadata from the GitHub API one page at a time.

        Only one page of runner dicts is held in memory at a time. This keeps
        ``runners`` and ``find_runners_by_label`` O(page_size) rather than
        O(total_runners), which matters in constrained environments such as
        128 MB Lambda functions.

        :return: An iterator of runner metadata dictionaries.
        :rtype: Iterator[dict]
        :raises ValueError: If a paginated response is missing the ``runners`` key.
        """
        url = f"{_GITHUB_API_URL}/orgs/{self._github.org}/actions/runners"
        while url:
            # Each page is its own request with its own retries, so a retried page is still yielded once.
            response = _request("GET", url, headers=self._github_headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            runners_page = data.get("runners")
            if runners_page is None:
                raise ValueError(
                    f"Unexpected GitHub API response from {url} — 'runners' key missing. "
                    f"Keys present: {list(data.keys())}"
                )
            yield from runners_page
            url = response.links.get("next", {}).get("url")

    def _ensure_present_secret(self, registration_token_secret):
        """
        Ensure a registration token secret is present in AWS Secrets Manager.

        This method checks if the specified secret exists. If it does not exist,
        it creates the secret with the registration token.

        :param registration_token_secret: The name of the secret to ensure presence.
        :type registration_token_secret: str
        :raises ClientError: If an unexpected AWS error occurs.
        """
        secret = Secret(registration_token_secret, region=self._region, role_arn=self._role_arn)
        secret.ensure_present(
            value=self.registration_token,
            description="GitHub Actions runner registration token",
        )

    def _ensure_absent_secret(self, registration_token_secret):
        """
        Ensure a registration token secret is absent in AWS Secrets Manager.

        This method checks if the specified secret exists. If it does exist,
        it deletes the secret.

        :param registration_token_secret: The name of the secret to ensure absence.
        :type registration_token_secret: str
        :raises ClientError: If an unexpected AWS error occurs.
        """
        secret = Secret(registration_token_secret, region=self._region, role_arn=self._role_arn)
        secret.ensure_absent(force=True)


class JWTSigner(ABC):  # pylint: disable=too-few-public-methods
    """
    Signs the JWT that a GitHub App authenticates with.

    :class:`GitHubAppTokenSource` calls :meth:`sign` once for every request it
    makes as the App, with the claims that :class:`github.Auth.AppAuth` builds.
    An implementation must not log its key, the JWT or the signature.
    """

    @abstractmethod
    def sign(self, payload: dict) -> str:
        """
        Sign a JWT payload with RS256.

        :param payload: The JWT claims: ``iat``, ``exp`` and ``iss``.
        :type payload: dict
        :return: The signed JWT in compact form, ``header.payload.signature``.
        :rtype: str
        """


class PEMSecretSigner(JWTSigner):  # pylint: disable=too-few-public-methods
    """
    Signs GitHub App JWTs with the App's private key, read from AWS Secrets Manager.

    This is how :func:`get_tmp_token` signs. Anyone who can read the secret can
    copy the key and sign as the App. :class:`KMSSigner` keeps the key in KMS
    instead.

    The secret is read on the first :meth:`sign` call. The key is then kept in
    memory for the life of the signer, so a change to the secret takes effect
    in a new signer.

    :param pem_key_secret: Name or ARN of the secret that holds the App's private key in PEM format.
    :type pem_key_secret: str
    :param region: AWS region of the secret. If omitted, uses the default region.
    :type region: str
    :param role_arn: IAM role ARN to assume for cross-account access.
    :type role_arn: str
    :param session: boto3 session to create the Secrets Manager client from, instead of ``role_arn``.
    :type session: boto3.Session
    """

    def __init__(self, pem_key_secret: str, region: str = None, role_arn: str = None, session=None):
        self._secret = Secret(pem_key_secret, region=region, role_arn=role_arn, session=session)
        self.__private_key = None
        # PyGithub's own signer, the one GithubIntegration(app_id, private_key) used before. It calls
        # _read_private_key() for every signature.
        self._sign_func = AppAuth.create_jwt_sign(self._read_private_key, DEFAULT_JWT_ALGORITHM)

    def sign(self, payload: dict) -> str:
        """
        Sign a JWT payload with RS256 and the App's private key.

        :param payload: The JWT claims: ``iat``, ``exp`` and ``iss``.
        :type payload: dict
        :return: The signed JWT in compact form, ``header.payload.signature``.
        :rtype: str
        :raises IHSecretNotFound: If the secret does not exist.
        :raises botocore.exceptions.ClientError: If Secrets Manager returns another error.
        """
        signed = self._sign_func(payload)
        return signed.decode("ascii") if isinstance(signed, bytes) else signed

    def _read_private_key(self) -> str:
        """
        Return the App's private key, reading the secret the first time.

        :return: The private key in PEM format.
        :rtype: str
        """
        if self.__private_key is None:
            self.__private_key = self._secret.value
        return self.__private_key


class KMSSigner(JWTSigner):  # pylint: disable=too-few-public-methods
    """
    Signs GitHub App JWTs with ``kms:Sign``. The App's private key stays in KMS.

    The KMS key must be an asymmetric key with key spec ``RSA_2048`` and key
    usage ``SIGN_VERIFY``, whose key material is imported from the App's
    private key. GitHub generates the App key and doesn't accept one made
    elsewhere, so the key is imported, not created in KMS.

    The caller needs ``kms:Sign`` on the key. The IAM condition
    ``kms:SigningAlgorithm = RSASSA_PKCS1_V1_5_SHA_256`` limits the grant to
    the one algorithm this class uses.

    The KMS client is created on the first :meth:`sign` call and reused for
    every later call on the same signer, so a warm AWS Lambda that keeps the
    signer doesn't create a client per token. With ``role_arn``, the client
    keeps the assumed role's temporary credentials, as other clients in this
    library do: create a new signer when they expire.

    Errors from KMS, such as ``AccessDeniedException``, ``DisabledException``
    or ``KMSInvalidStateException``, reach the caller unchanged, as
    :class:`botocore.exceptions.ClientError`.

    :param key_id: The KMS key, in any form ``kms:Sign`` accepts: key ID, key ARN, alias name (``alias/...``) or
        alias ARN. A key in another AWS account needs the key ARN or the alias ARN.
    :type key_id: str
    :param region: AWS region of the key. If omitted, uses the default region.
    :type region: str
    :param role_arn: IAM role ARN to assume for cross-account access.
    :type role_arn: str
    :param session: boto3 session to create the KMS client from, instead of ``role_arn``.
    :type session: boto3.Session
    """

    def __init__(self, key_id: str, region: str = None, role_arn: str = None, session=None):
        self._key_id = key_id
        self._region = region
        self._role_arn = role_arn
        self._session = session
        self.__client = None

    def sign(self, payload: dict) -> str:
        """
        Sign a JWT payload with RS256 through ``kms:Sign``.

        The signing input is ``base64url(header) + "." + base64url(payload)``,
        both as compact JSON and base64url without padding, the same bytes that
        PyJWT writes. PKCS#1 v1.5 signatures are deterministic, so the JWT is
        identical to the one :class:`PEMSecretSigner` makes with the same key.

        :param payload: The JWT claims: ``iat``, ``exp`` and ``iss``.
        :type payload: dict
        :return: The signed JWT in compact form, ``header.payload.signature``.
        :rtype: str
        :raises botocore.exceptions.ClientError: If KMS refuses to sign, for example
            ``AccessDeniedException``, ``DisabledException`` or ``KMSInvalidStateException``.
        """
        signing_input = f"{_base64url_json(_JWT_HEADER)}.{_base64url_json(payload)}"
        response = self._client.sign(
            KeyId=self._key_id,
            Message=signing_input.encode("ascii"),
            MessageType="RAW",
            SigningAlgorithm=_KMS_SIGNING_ALGORITHM,
        )
        return f"{signing_input}.{_base64url(response['Signature'])}"

    @property
    def _client(self):
        """
        The KMS client, created on first use.

        :return: A boto3 KMS client.
        """
        if self.__client is None:
            if self._session is not None:
                self.__client = self._session.client("kms", region_name=self._region)
            else:
                self.__client = get_client("kms", role_arn=self._role_arn, region=self._region)
        return self.__client


class GitHubTokenSource(ABC):  # pylint: disable=too-few-public-methods
    """
    Where a caller gets GitHub App installation tokens.

    Write callers against this interface rather than a concrete source. Then
    a different source replaces the current one without changing the callers'
    calls. :class:`GitHubAppTokenSource` mints tokens as the App. A token
    broker, which mints tokens for its callers so they hold no App credentials
    at all, can implement this interface later.
    """

    @abstractmethod
    def installation_token(self, github_org_name: str, permissions: Optional[dict] = None) -> str:
        """
        Return an installation access token for the App's installation in an organization.

        :param github_org_name: The GitHub organization the App is installed in.
        :type github_org_name: str
        :param permissions: The permissions the token gets, as GitHub's API names them, for example
            ``{"organization_self_hosted_runners": "write"}``. ``None`` gets all the permissions of the
            installation.
        :type permissions: dict
        :return: The installation access token. GitHub expires it after one hour.
        :rtype: str
        """


class GitHubAppTokenSource(GitHubTokenSource):  # pylint: disable=too-few-public-methods
    """
    Mints GitHub App installation tokens as the App, with JWTs from a signer.

    Every request it makes as the App carries a new JWT from ``signer``: the
    list of the App's installations, the lookup of each organization
    installation's account, and the token exchange. Each JWT expires
    ``MAX_JWT_EXPIRY`` (10 minutes) after it is made.

    Example::

        source = GitHubAppTokenSource(
            123456,
            KMSSigner("arn:aws:kms:us-west-2:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab"),
        )
        token = source.installation_token(
            "my-org", permissions={"organization_self_hosted_runners": "write"}
        )
        github = GitHubAuth(token=token, org="my-org")

    .. note::
        This class logs no key, JWT or token. At DEBUG, the libraries under
        it do: PyGithub logs response bodies on the ``github`` logger, the
        installation token among them, and botocore logs them on the
        ``botocore`` loggers, the KMS signature or the PEM secret among them.
        Keep those loggers above DEBUG where logs are kept.
        :func:`infrahouse_core.logging.setup_logging` keeps botocore above
        DEBUG unless ``debug_botocore`` is set.

    :param app_id: The GitHub App ID, or its client ID.
    :type app_id: int or str
    :param signer: Signs the App JWTs.
    :type signer: JWTSigner
    """

    def __init__(self, app_id: Union[int, str], signer: JWTSigner):
        self._app_id = app_id
        self._signer = signer

    def installation_token(self, github_org_name: str, permissions: Optional[dict] = None) -> str:
        """
        Return an installation access token for the App's installation in an organization.

        The installation is the App's ``Organization`` installation whose
        account login is ``github_org_name``. ``permissions`` reaches GitHub
        unchanged; GitHub rejects permissions it doesn't know and permissions
        the installation doesn't have.

        :param github_org_name: The GitHub organization the App is installed in.
        :type github_org_name: str
        :param permissions: The permissions the token gets, as GitHub's API names them, for example
            ``{"organization_self_hosted_runners": "write"}``. ``None`` gets all the permissions of the
            installation.
        :type permissions: dict
        :return: The installation access token. GitHub expires it after one hour.
        :rtype: str
        :raises github.GithubException: If GitHub returns an error status when listing the App's
            installations or exchanging the JWT for a token, for example 422 for permissions the
            installation doesn't have. ``status`` holds the HTTP status.
        :raises requests.HTTPError: If GitHub returns an error status when asked which account
            an installation belongs to.
        :raises RuntimeError: If the GitHub App has no installation in ``github_org_name``.
        :raises botocore.exceptions.ClientError: If the signer's AWS call fails, for example
            ``kms:Sign`` with ``AccessDeniedException``.
        """
        # iss must be a string: PyJWT 2.10 and later refuse to sign another type. PyGithub 2.7 and later convert
        # the App ID themselves; 2.6 doesn't.
        auth = AppAuth(str(self._app_id), sign_func=self._signer.sign, jwt_expiry=MAX_JWT_EXPIRY)
        with GithubIntegration(auth=auth, base_url=_GITHUB_API_URL) as integration:
            for installation in integration.get_installations():
                if installation.target_type == "Organization":
                    if github_org_name == _get_org_name(auth, installation.id):
                        return integration.get_access_token(installation.id, permissions=permissions).token

        raise RuntimeError(f"Could not find installation of {self._app_id} in organization {github_org_name}")


def get_tmp_token(
    gh_app_id: int,
    pem_key_secret: str,
    github_org_name: str,
    region: str = None,
    role_arn: str = None,
) -> str:
    """
    Generate a temporary GitHub token from GitHUb App PEM key.
    The GitHub App must be created in your org, can be found in
    https://github.com/organizations/YOUR_ORG/settings/apps/infrahouse-github-terraform

    The token has all the permissions of the App's installation. This is
    :class:`GitHubAppTokenSource` with a :class:`PEMSecretSigner`; use those
    directly to request fewer permissions, or :class:`KMSSigner` to keep the
    key out of Secrets Manager.

    :param gh_app_id: GitHub Application identifier.
    :type gh_app_id: int
    :param pem_key_secret: Secret ARN with the PEM key.
    :type pem_key_secret: str
    :param github_org_name: GitHub Organization. Used to find GitHub App installation.
    :param region: AWS region for Secrets Manager operations.
    :type region: str
    :param role_arn: IAM role ARN to assume for cross-account access.
    :type role_arn: str
    :return: GitHub token
    :rtype: str
    :raises requests.HTTPError: If GitHub returns an error status when asked which account
        an installation belongs to.
    :raises github.GithubException: If GitHub returns an error status when listing the App's
        installations or exchanging the JWT for a token.
    :raises RuntimeError: If the GitHub App has no installation in ``github_org_name``.
    :raises IHSecretNotFound: If the secret ``pem_key_secret`` does not exist.
    """
    signer = PEMSecretSigner(pem_key_secret, region=region, role_arn=role_arn)
    return GitHubAppTokenSource(gh_app_id, signer).installation_token(github_org_name)


def _base64url(data: bytes) -> str:
    """
    Encode bytes as base64url without padding, as JWTs use it.

    :param data: The bytes to encode.
    :type data: bytes
    :return: The encoded string.
    :rtype: str
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_json(value: dict) -> str:
    """
    Encode a dict as compact JSON in base64url without padding, as PyJWT encodes JWT headers and payloads.

    :param value: The JWT header or payload.
    :type value: dict
    :return: The encoded segment.
    :rtype: str
    """
    return _base64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _get_org_name(app_auth: AppAuth, installation_id: int) -> str:
    """
    Return the login of the account a GitHub App installation belongs to.

    :param app_auth: The App's authentication, used to sign the request with a JWT.
    :type app_auth: github.Auth.AppAuth
    :param installation_id: The GitHub App installation ID.
    :type installation_id: int
    :return: The account login, for example the organization name.
    :rtype: str
    :raises requests.HTTPError: If the GitHub API returns a non-2xx status.
    """
    url = f"{_GITHUB_API_URL}/app/installations/{installation_id}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_auth.create_jwt()}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = _request("GET", url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()["account"]["login"]


@cache
def _get_session() -> Session:
    """
    Return the :class:`requests.Session` for GitHub REST API calls.

    The session is created on the first call and reused for the life of the
    process, so a warm AWS Lambda keeps its connection pool between
    invocations.

    The session retries connection errors, dropped connections, read
    timeouts, and responses with a status in ``_RETRY_STATUS_FORCELIST``,
    for the methods in ``_RETRY_ALLOWED_METHODS``. It honours the
    ``Retry-After`` header of 429 and 503 responses. When the retries run
    out on an HTTP status, it returns the last response instead of raising,
    so the caller's ``raise_for_status()`` raises
    :class:`requests.HTTPError`, as it did before retries existed.

    The ``timeout`` that each caller passes applies to every attempt, not to
    the call as a whole.

    The retrying adapter is mounted for both ``https://`` and ``http://``.
    The GitHub API is HTTPS only; ``http://`` lets tests point
    ``_GITHUB_API_URL`` at a local plain-HTTP server.

    Call the API through :func:`_request`, not through this session directly,
    so that exhausted read timeouts are reported as ``ReadTimeout``.

    :return: A session with a retrying adapter mounted.
    :rtype: requests.Session
    """
    retry = Retry(
        total=_RETRY_TOTAL,
        connect=_RETRY_TOTAL,
        read=_RETRY_TOTAL,
        status=_RETRY_TOTAL,
        backoff_factor=_RETRY_BACKOFF_FACTOR,
        status_forcelist=_RETRY_STATUS_FORCELIST,
        allowed_methods=_RETRY_ALLOWED_METHODS,
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _request(method: str, url: str, headers: dict, timeout: float) -> Response:
    """
    Send one GitHub REST API request through the retrying session.

    When a read timeout exhausts the retries, requests reports it as
    :class:`requests.ConnectionError`. Without retries the same failure is
    :class:`requests.ReadTimeout`, which is a :class:`requests.Timeout` and
    not a ``ConnectionError``. This function re-raises it as ``ReadTimeout``
    so that callers catching ``requests.Timeout`` keep working.

    :param method: HTTP method, for example ``"GET"``.
    :type method: str
    :param url: The full request URL.
    :type url: str
    :param headers: Request headers, including the authorization header.
    :type headers: dict
    :param timeout: Connect and read timeout in seconds, applied to every attempt.
    :type timeout: float
    :return: The response. An HTTP error status is returned, not raised.
    :rtype: requests.Response
    :raises requests.ReadTimeout: If every attempt timed out reading the response.
    :raises requests.ConnectionError: If a network error persisted through the retries.
    """
    try:
        return _get_session().request(method, url, headers=headers, timeout=timeout)
    except RequestsConnectionError as err:
        cause = err.args[0] if err.args else None
        if isinstance(cause, MaxRetryError) and isinstance(cause.reason, ReadTimeoutError):
            raise ReadTimeout(cause, request=err.request) from err
        raise
