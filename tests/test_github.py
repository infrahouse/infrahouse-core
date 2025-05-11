from unittest import mock

import pytest
from requests.exceptions import HTTPError

from src.infrahouse_core.github import GitHubActionsRunner, GitHubAuth


@pytest.fixture
def mock_runner_data():
    return {
        "id": 252,
        "name": "test-runner",
        "os": "linux",
        "status": "online",
        "busy": False,
        "labels": [
            {"id": 1, "name": "self-hosted", "type": "read-only"},
            {"id": 2, "name": "linux", "type": "read-only"},
            {"id": 3, "name": "instance_id:i-04d5f0304e328f983", "type": "custom"},
        ],
    }


@pytest.fixture
def github_auth():
    return GitHubAuth("test-token", "test-org")


@pytest.fixture
def runner(github_auth, mock_runner_data):
    with mock.patch("src.infrahouse_core.github.get") as mock_get:
        mock_response = mock.Mock()
        mock_response.json.return_value = mock_runner_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        yield GitHubActionsRunner(252, github_auth)


def test_runner_initialization(runner, github_auth):
    assert runner.runner_id == 252
    assert runner._github == github_auth


def test_runner_properties(runner, mock_runner_data):
    assert runner.name == mock_runner_data["name"]
    assert runner.os == mock_runner_data["os"]
    assert runner.status == mock_runner_data["status"]
    assert runner.busy == mock_runner_data["busy"]
    assert runner.labels == ["self-hosted", "linux", "instance_id:i-04d5f0304e328f983"]
    assert runner.instance_id == "i-04d5f0304e328f983"


def test_runner_refresh(runner, mock_runner_data):
    # First call should use cached data
    assert runner.status == mock_runner_data["status"]

    # Update mock data
    mock_runner_data["status"] = "offline"

    # Force refresh by accessing status again
    assert runner.status == "offline"


def test_runner_http_error(github_auth):
    with mock.patch("requests.get") as mock_get:
        mock_response = mock.Mock()
        mock_response.raise_for_status.side_effect = HTTPError("API Error")
        mock_get.return_value = mock_response

        with pytest.raises(HTTPError):
            runner = GitHubActionsRunner(252, github_auth)
            _ = runner.status


def test_runner_no_instance_id(github_auth):
    mock_data = {
        "id": 252,
        "name": "test-runner",
        "os": "linux",
        "status": "online",
        "busy": False,
        "labels": [
            {"id": 1, "name": "self-hosted", "type": "read-only"},
            {"id": 2, "name": "linux", "type": "read-only"},
        ],
    }

    with mock.patch("src.infrahouse_core.github.get") as mock_get:
        mock_response = mock.Mock()
        mock_response.json.return_value = mock_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        runner = GitHubActionsRunner(252, github_auth)
        assert runner.instance_id is None


def test_runner_headers(github_auth):
    runner = GitHubActionsRunner(252, github_auth)
    headers = runner._github_headers

    assert headers["Authorization"] == "Bearer test-token"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
