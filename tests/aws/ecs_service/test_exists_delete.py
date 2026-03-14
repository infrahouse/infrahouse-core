"""Tests for ECSService."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.ecs_service import ECSService

CLUSTER = "my-cluster"
SERVICE = "my-service"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def _service_description(**overrides):
    """Return a realistic ECS service description dict with optional overrides."""
    desc = {
        "serviceName": SERVICE,
        "clusterArn": f"arn:aws:ecs:us-east-1:123456789012:cluster/{CLUSTER}",
        "status": "ACTIVE",
        "taskDefinition": "arn:aws:ecs:us-east-1:123456789012:task-definition/my-task:3",
        "desiredCount": 2,
        "runningCount": 2,
        "deployments": [
            {
                "id": "ecs-svc/123",
                "status": "PRIMARY",
                "rolloutState": "COMPLETED",
                "desiredCount": 2,
                "runningCount": 2,
            }
        ],
    }
    desc.update(overrides)
    return desc


# -- constructor properties ---------------------------------------------------


def test_cluster_name():
    """cluster_name returns the cluster passed to the constructor."""
    svc = ECSService(CLUSTER, SERVICE)
    assert svc.cluster_name == CLUSTER


def test_service_name():
    """service_name returns the service passed to the constructor."""
    svc = ECSService(CLUSTER, SERVICE)
    assert svc.service_name == SERVICE


# -- exists -------------------------------------------------------------------


def test_exists_active():
    """exists returns True when the service status is ACTIVE."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": [_service_description()]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.exists is True
        mock_client.describe_services.assert_called_once_with(cluster=CLUSTER, services=[SERVICE])


def test_exists_inactive():
    """exists returns False when the service status is INACTIVE."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": [_service_description(status="INACTIVE")]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.exists is False


def test_exists_empty_response():
    """exists returns False when describe_services returns no services."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": []}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.exists is False


# -- status -------------------------------------------------------------------


def test_status():
    """status returns the service status string."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": [_service_description(status="DRAINING")]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.status == "DRAINING"


# -- task_definition_arn ------------------------------------------------------


def test_task_definition_arn():
    """task_definition_arn returns the ARN from describe."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    expected_arn = "arn:aws:ecs:us-east-1:123456789012:task-definition/my-task:3"
    mock_client.describe_services.return_value = {"services": [_service_description()]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.task_definition_arn == expected_arn


# -- desired_count / running_count -------------------------------------------


def test_desired_count():
    """desired_count returns the value from describe."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": [_service_description(desiredCount=5)]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.desired_count == 5


def test_running_count():
    """running_count returns the value from describe."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": [_service_description(runningCount=3)]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.running_count == 3


# -- is_steady_state ----------------------------------------------------------


def test_is_steady_state_true():
    """is_steady_state returns True when running == desired and all deployments completed."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": [_service_description()]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.is_steady_state is True


def test_is_steady_state_false_count_mismatch():
    """is_steady_state returns False when running != desired."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": [_service_description(desiredCount=3, runningCount=1)]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.is_steady_state is False


def test_is_steady_state_false_in_progress_deployment():
    """is_steady_state returns False when a deployment is still in progress."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    desc = _service_description(
        deployments=[
            {"id": "ecs-svc/123", "status": "PRIMARY", "rolloutState": "IN_PROGRESS"},
        ]
    )
    mock_client.describe_services.return_value = {"services": [desc]}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert svc.is_steady_state is False


# -- _describe raises on missing service --------------------------------------


def test_describe_raises_on_missing():
    """_describe raises RuntimeError when service is not found."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_services.return_value = {"services": []}

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(RuntimeError, match="not found"):
            svc.status


# -- delete -------------------------------------------------------------------


def test_delete():
    """delete() scales to 0 then force-deletes."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        svc.delete()

    mock_client.update_service.assert_called_once_with(cluster=CLUSTER, service=SERVICE, desiredCount=0)
    mock_client.delete_service.assert_called_once_with(cluster=CLUSTER, service=SERVICE, force=True)


def test_delete_not_exists_service_not_found():
    """delete() on a non-existent service is a no-op (ServiceNotFoundException)."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.update_service.side_effect = _make_client_error("ServiceNotFoundException")

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        svc.delete()  # Should not raise


def test_delete_not_exists_cluster_not_found():
    """delete() on a non-existent cluster is a no-op (ClusterNotFoundException)."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.update_service.side_effect = _make_client_error("ClusterNotFoundException")

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        svc.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    svc = ECSService(CLUSTER, SERVICE, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.update_service.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ECSService, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            svc.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
