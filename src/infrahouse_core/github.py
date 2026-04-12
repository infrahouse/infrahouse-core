"""
GitHub Actions
"""

from dataclasses import dataclass
from logging import getLogger
from typing import Iterator, List, Optional

from cached_property import cached_property_with_ttl
from github import GithubIntegration
from github.Consts import MAX_JWT_EXPIRY
from requests import HTTPError, delete, get, post

from infrahouse_core.aws.secretsmanager import Secret

LOG = getLogger(__name__)


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
                response = get(
                    f"https://api.github.com/orgs/{self._github.org}/actions/runners/{self._runner_id}",
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

        :param github: GitHub authentication object.
        :type github: GitHubAuth
        :param region: AWS region for Secrets Manager operations.
        :type region: str
        :param role_arn: IAM role ARN to assume for cross-account access.
        :type role_arn: str
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
        response = post(
            f"https://api.github.com/orgs/{self._github.org}/actions/runners/registration-token",
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

        :param runner: The runner to de-register.
        :type runner: GitHubActionsRunner
        :raises requests.HTTPError: If the GitHub API returns a non-2xx status
            (for example, 404 if the runner was already removed).
        """
        response = delete(
            f"https://api.github.com/orgs/{self._github.org}/actions/runners/{runner.runner_id}",
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
        url = f"https://api.github.com/orgs/{self._github.org}/actions/runners"
        while url:
            response = get(url, headers=self._github_headers, timeout=10)
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
    """
    secret = Secret(pem_key_secret, region=region, role_arn=role_arn)
    github_client = GithubIntegration(
        gh_app_id,
        secret.value,
        jwt_expiry=MAX_JWT_EXPIRY,
    )
    for installation in github_client.get_installations():
        if installation.target_type == "Organization":
            if github_org_name == _get_org_name(github_client, installation.id):
                return github_client.get_access_token(installation_id=installation.id).token

    raise RuntimeError(f"Could not find installation of {gh_app_id} in organization {github_org_name}")


def _get_org_name(github_client: GithubIntegration, installation_id: int) -> str:
    url = f"https://api.github.com/app/installations/{installation_id}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_client.create_jwt()}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = get(url, headers=headers, timeout=30)
    return response.json()["account"]["login"]
