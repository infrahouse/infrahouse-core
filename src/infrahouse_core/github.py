"""
GitHub Actions
"""

from dataclasses import dataclass
from logging import getLogger
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError
from cached_property import cached_property_with_ttl
from github import GithubIntegration
from github.Consts import MAX_JWT_EXPIRY
from requests import HTTPError, delete, get, post

from infrahouse_core.aws import get_secret

LOG = getLogger()


@dataclass
class GitHubAuth:
    """
    Authentication information for GitHub API access.

    This class holds the necessary credentials to authenticate with the GitHub API.
    It is used by other classes in this module to make authenticated API calls.

    :param token: GitHub Personal Access Token or GitHub App token for authentication
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
    """

    def __init__(self, github: GitHubAuth):
        """
        Initialize the GitHubActions manager.

        :param github: GitHub authentication object.
        :type github: GitHubAuth
        """
        self._github = github
        self._runners = None

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
    def runners(self) -> List[GitHubActionsRunner]:
        """
        Retrieve a list of all self-hosted runners for the organization.

        :return: A list of GitHubActionsRunner objects.
        :rtype: list[GitHubActionsRunner]
        """
        if self._runners is None:
            self._runners = [
                GitHubActionsRunner(r["id"], self._github, runner_data=r) for r in self._get_github_runners()
            ]

        return self._runners

    def deregister_runner(self, runner: GitHubActionsRunner):
        """
        De-register a runner from the GitHub organization.

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

    def find_runners_by_label(self, label: str) -> List[GitHubActionsRunner]:
        """
        Find all runners that have the specified label.

        This method iterates over all available runners and collects
        those that contain the specified label in their list of labels.

        :param label: The label to search for.
        :type label: str
        :return: A list of GitHubActionsRunner objects that match the label,
                 or an empty list if none are found.
        :rtype: List[GitHubActionsRunner]
        """
        # Filter runners by checking if the label is present in each runner's labels
        return [runner for runner in self.runners if label in runner.labels]

    @property
    def _github_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._github.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get_github_runners(self) -> List[dict]:
        """
        Internal method to retrieve raw runner data from the GitHub API.

        :return: A list of runner metadata dictionaries.
        :rtype: list[dict]
        """
        runners = []
        url = f"https://api.github.com/orgs/{self._github.org}/actions/runners"
        while url:
            response = get(url, headers=self._github_headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            runners.extend(data["runners"])
            url = response.links.get("next", {}).get("url")
        return runners

    def _ensure_present_secret(self, registration_token_secret):
        """
        Ensure a registration token secret is present in AWS Secrets Manager.

        This method checks if the specified secret exists. If it does not exist,
        it creates the secret with the registration token. If an error other than
        'ResourceNotFoundException' occurs during the check, it raises the exception.

        :param registration_token_secret: The name of the secret to ensure presence.
        :type registration_token_secret: str
        :raises ClientError: If an error occurs that is not a 'ResourceNotFoundException'.
        """
        secretsmanager_client = boto3.client("secretsmanager")
        try:
            secretsmanager_client.describe_secret(SecretId=registration_token_secret)

        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                secretsmanager_client.create_secret(
                    Name=registration_token_secret,
                    Description="GitHub Actions runner registration token",
                    SecretString=self.registration_token,
                )
            else:
                raise

    @staticmethod
    def _ensure_absent_secret(registration_token_secret):
        """
        Ensure a registration token secret is absent in AWS Secrets Manager.

        This method checks if the specified secret exists. If it does exist,
        it deletes the secret. If an error other than 'ResourceNotFoundException'
        occurs during the check, it raises the exception.

        :param registration_token_secret: The name of the secret to ensure absence.
        :type registration_token_secret: str
        :raises ClientError: If an error occurs that is not a 'ResourceNotFoundException'.
        """
        secretsmanager_client = boto3.client("secretsmanager")
        try:
            secretsmanager_client.describe_secret(SecretId=registration_token_secret)
            secretsmanager_client.delete_secret(SecretId=registration_token_secret)

        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                return

            LOG.error("Error occurred while deleting secret: %s", err)
            raise


def get_tmp_token(gh_app_id: int, pem_key_secret: str, github_org_name: str) -> str:
    """
    Generate a temporary GitHub token from GitHUb App PEM key.
    The GitHub App must be created in your org, can be found in
    https://github.com/organizations/YOUR_ORG/settings/apps/infrahouse-github-terraform

    :param gh_app_id: GitHub Application identifier.
    :type gh_app_id: int
    :param pem_key_secret: Secret ARN with the PEM key.
    :type pem_key_secret: str
    :param github_org_name: GitHub Organization. Used to find GitHub App installation.
    :return: GitHub token
    :rtype: str
    """
    secretsmanager_client = boto3.client("secretsmanager")
    github_client = GithubIntegration(
        gh_app_id,
        get_secret(secretsmanager_client, pem_key_secret),
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
    response = get(url, headers=headers, timeout=600)
    return response.json()["account"]["login"]
