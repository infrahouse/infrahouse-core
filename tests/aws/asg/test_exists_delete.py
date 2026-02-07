"""Tests for ASG.exists and ASG.delete()."""

from unittest import mock

from botocore.exceptions import ClientError

from infrahouse_core.aws.asg import ASG


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def test_exists_true():
    """exists returns True when the ASG is found."""
    asg = ASG("my-asg", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": [{"AutoScalingGroupName": "my-asg"}]}
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert asg.exists is True
        mock_client.describe_auto_scaling_groups.assert_called_once_with(AutoScalingGroupNames=["my-asg"])


def test_exists_false():
    """exists returns False when the ASG is not found."""
    asg = ASG("my-asg", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_auto_scaling_groups.return_value = {"AutoScalingGroups": []}
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert asg.exists is False


def test_delete():
    """delete() calls delete_auto_scaling_group with ForceDelete."""
    asg = ASG("my-asg", region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        asg.delete()
        mock_client.delete_auto_scaling_group.assert_called_once_with(
            AutoScalingGroupName="my-asg",
            ForceDelete=True,
        )


def test_delete_not_exists():
    """delete() on a non-existent ASG is a no-op."""
    asg = ASG("my-asg", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_auto_scaling_group.side_effect = _make_client_error("ValidationError")
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        asg.delete()  # Should not raise
        mock_client.delete_auto_scaling_group.assert_called_once()


def test_delete_no_force():
    """delete(force_delete=False) passes ForceDelete=False."""
    asg = ASG("my-asg", region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        asg.delete(force_delete=False)
        mock_client.delete_auto_scaling_group.assert_called_once_with(
            AutoScalingGroupName="my-asg",
            ForceDelete=False,
        )


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    asg = ASG("my-asg", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_auto_scaling_group.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        try:
            asg.delete()
            assert False, "Should have raised ClientError"
        except ClientError as err:
            assert err.response["Error"]["Code"] == "AccessDeniedException"
