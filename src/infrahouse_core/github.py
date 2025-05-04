"""
GitHub Actions
"""

from logging import getLogger
from typing import Dict, List

from requests import delete, get

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
