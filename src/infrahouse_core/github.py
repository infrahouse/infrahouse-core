"""
GitHub Actions
"""

from logging import getLogger
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError
from github import GithubIntegration
from github.Consts import MAX_JWT_EXPIRY
from requests import delete, get, post

from infrahouse_core.aws import get_secret
from infrahouse_core.aws.asg_instance import ASGInstance

LOG = getLogger()


class GitHubActions:
    """
    The GitHubActions works with self-hosted action runners

    :param github_token: A GitHub API token with admin permissions.
    :type github_token: str
    :param org: GitHub organization name.
    :type org: str
    """

    def __init__(self, github_token: str, org: str):
        self._token = github_token
        self._org = org
        self._runners = None

    @property
    def registration_token(self):
        """
        Request a registration token from GitHub.
        """
        response = post(
            f"https://api.github.com/orgs/{self._org}/actions/runners/registration-token",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["token"]

    @property
    def runners(self) -> List[Dict]:
        """
        :return: A list of runners. Each runner is a dictionary.
        :rtype: list(dict)
        """
        if self._runners is None:
            self._runners = self._get_github_runners()

        return self._runners

    def deregister_runner(
        self,
        asg_instance: ASGInstance,
        runner_id: int,
    ):
        """Remove the instance from DNS."""
        print(f"De-registering runner {asg_instance.instance_id} from {self._org}")
        response = delete(
            f"https://api.github.com/orgs/{self._org}/actions/runners/{runner_id}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        response.raise_for_status()
        print(f"Runner {runner_id}:{asg_instance.instance_id} is successfully deregistered.")

    def ensure_registration_token(self, registration_token_secret):
        """
        Make sure a runner registration token is requested and saved in the Secretsmanager.

        :param registration_token_secret: Secret name where to store the registration token.
        :type registration_token_secret: str
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
                raise  # Re-raise other unexpected exceptions

    def find_runner_by_label(self, label):
        """
        Find a first runner that has a given label. None if not found.
        """
        LOG.info("Looking for a runner with label %s", label)
        for runner in self.runners:
            labels = [l["name"] for l in runner["labels"]]
            if label in labels:
                LOG.info("Found %s!", runner["name"])
                return runner

        LOG.warning("Couldn't find a runner with label %s", label)
        return None

    def _get_github_runners(self):
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
        }

        response = get(f"https://api.github.com/orgs/{self._org}/actions/runners", headers=headers, timeout=10)
        response.raise_for_status()

        return response.json()["runners"]


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


def _get_org_name(github_client, installation_id):
    url = f"https://api.github.com/app/installations/{installation_id}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_client.create_jwt()}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = get(url, headers=headers, timeout=600)
    return response.json()["account"]["login"]
