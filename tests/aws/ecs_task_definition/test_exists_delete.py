"""Tests for ECSTaskDefinition."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.ecs_task_definition import ECSTaskDefinition

TASK_DEF_ARN = "arn:aws:ecs:us-west-2:303467602807:task-definition/my-task:8"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def _task_definition(**overrides):
    """Return a realistic task definition dict with optional overrides."""
    td = {
        "taskDefinitionArn": TASK_DEF_ARN,
        "status": "ACTIVE",
        "containerDefinitions": [
            {
                "name": "app",
                "image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-app:latest",
            },
        ],
    }
    td.update(overrides)
    return td


# -- task_definition_arn ------------------------------------------------------


def test_task_definition_arn():
    """task_definition_arn returns the ARN passed to the constructor."""
    td = ECSTaskDefinition(TASK_DEF_ARN)
    assert td.task_definition_arn == TASK_DEF_ARN


# -- exists -------------------------------------------------------------------


def test_exists_active():
    """exists returns True when the task definition status is ACTIVE."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    mock_client.describe_task_definition.return_value = {"taskDefinition": _task_definition()}

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert td.exists is True
        mock_client.describe_task_definition.assert_called_once_with(taskDefinition=TASK_DEF_ARN)


def test_exists_inactive():
    """exists returns False when the task definition status is INACTIVE."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    mock_client.describe_task_definition.return_value = {"taskDefinition": _task_definition(status="INACTIVE")}

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert td.exists is False


def test_exists_not_found():
    """exists returns False when the task definition does not exist (ClientException)."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    mock_client.describe_task_definition.side_effect = _make_client_error("ClientException")

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert td.exists is False


def test_exists_unexpected_error():
    """Unexpected errors from describe_task_definition are re-raised."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    mock_client.describe_task_definition.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = td.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# -- container_images ---------------------------------------------------------


def test_container_images_single():
    """container_images returns a single image URI."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    mock_client.describe_task_definition.return_value = {"taskDefinition": _task_definition()}

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert td.container_images == [
            "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-app:latest",
        ]


def test_container_images_multiple():
    """container_images returns image URIs from all container definitions."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    containers = [
        {"name": "app", "image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-app:v1.0"},
        {"name": "sidecar", "image": "123456789012.dkr.ecr.us-west-2.amazonaws.com/cw-agent:latest"},
    ]
    mock_client.describe_task_definition.return_value = {
        "taskDefinition": _task_definition(containerDefinitions=containers),
    }

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert td.container_images == [
            "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-app:v1.0",
            "123456789012.dkr.ecr.us-west-2.amazonaws.com/cw-agent:latest",
        ]


# -- delete -------------------------------------------------------------------


def test_delete():
    """delete() calls deregister_task_definition."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        td.delete()

    mock_client.deregister_task_definition.assert_called_once_with(taskDefinition=TASK_DEF_ARN)


def test_delete_not_exists():
    """delete() on a non-existent task definition is a no-op."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    mock_client.deregister_task_definition.side_effect = _make_client_error("ClientException")

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        td.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    td = ECSTaskDefinition(TASK_DEF_ARN, region="us-west-2")
    mock_client = mock.MagicMock()
    mock_client.deregister_task_definition.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ECSTaskDefinition, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            td.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
