from unittest import mock

import pytest

from infrahouse_core.github import GitHubActions, GitHubActionsRunner


def create_runner(runner_id, name, labels, os="linux", status="online", busy=False):
    runner = GitHubActionsRunner(runner_id, mock.MagicMock())
    runner_data = {
        "id": runner_id,
        "name": name,
        "os": os,
        "status": status,
        "busy": busy,
        "labels": labels,
    }
    setattr(runner, "_runner_data", runner_data)
    return runner


@pytest.fixture
def runner_1():
    labels = [
        {"id": 1, "name": "alpha", "type": "read-only"},
        {"id": 2, "name": "beta", "type": "read-only"},
    ]
    return create_runner(1, "runner1", labels)


@pytest.fixture
def runner_2():
    labels = [
        {"id": 1, "name": "gamma", "type": "read-only"},
    ]
    return create_runner(2, "runner2", labels)


@pytest.fixture
def runner_3():
    labels = [
        {"id": 1, "name": "alpha", "type": "read-only"},
        {"id": 2, "name": "delta", "type": "read-only"},
    ]
    return create_runner(3, "runner3", labels)


@pytest.fixture()
def gha_instance(runner_1, runner_2, runner_3):
    # Create a mock GitHubActions instance with runners.
    with mock.patch.object(
        GitHubActions, "runners", new_callable=mock.PropertyMock, return_value=[runner_1, runner_2, runner_3]
    ):
        yield GitHubActions(mock.MagicMock())


def test_find_runners_by_label_empty(gha_instance):
    # When there are no runners, the method should return an empty list.
    result = gha_instance.find_runners_by_label("any")
    assert result == []


def test_find_runners_by_label_found(gha_instance):
    # Should return only those runners that include the "alpha" label.
    result = gha_instance.find_runners_by_label("alpha")
    assert len(result) == 2
