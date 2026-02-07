"""Tests for EC2Instance.exists and EC2Instance.delete()."""

from unittest import mock

from botocore.exceptions import ClientError

from infrahouse_core.aws.ec2_instance import EC2Instance


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def _make_instance(instance_id="i-1234567890abcdef0", state="running"):
    """Create an EC2Instance with a mocked ec2 client returning the given state."""
    mock_client = mock.MagicMock()
    mock_client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "State": {"Name": state},
                        "Tags": [{"Key": "Name", "Value": "test"}],
                        "PrivateDnsName": "ip-10-0-0-1.ec2.internal",
                        "PrivateIpAddress": "10.0.0.1",
                    }
                ]
            }
        ]
    }
    instance = EC2Instance(instance_id=instance_id, ec2_client=mock_client)
    return instance, mock_client


def test_exists_running():
    """A running instance exists."""
    instance, _ = _make_instance(state="running")
    assert instance.exists is True


def test_exists_stopped():
    """A stopped instance exists."""
    instance, _ = _make_instance(state="stopped")
    assert instance.exists is True


def test_exists_terminated():
    """A terminated instance does not exist."""
    instance, _ = _make_instance(state="terminated")
    assert instance.exists is False


def test_exists_shutting_down():
    """A shutting-down instance does not exist."""
    instance, _ = _make_instance(state="shutting-down")
    assert instance.exists is False


def test_exists_not_found():
    """An instance that doesn't exist in AWS returns False."""
    instance_id = "i-0abcdef1234567890"
    mock_client = mock.MagicMock()
    mock_client.describe_instances.side_effect = _make_client_error("InvalidInstanceID.NotFound")

    instance = EC2Instance(instance_id=instance_id, ec2_client=mock_client)
    assert instance.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    instance_id = "i-1234567890abcdef0"
    mock_client = mock.MagicMock()
    mock_client.describe_instances.side_effect = _make_client_error("UnauthorizedAccess")

    instance = EC2Instance(instance_id=instance_id, ec2_client=mock_client)
    try:
        _ = instance.exists
        assert False, "Should have raised ClientError"
    except ClientError as err:
        assert err.response["Error"]["Code"] == "UnauthorizedAccess"


def test_delete_running():
    """delete() terminates a running instance."""
    instance, mock_client = _make_instance(state="running")
    instance.delete()
    mock_client.terminate_instances.assert_called_once_with(InstanceIds=["i-1234567890abcdef0"])


def test_delete_already_terminated():
    """delete() on a terminated instance is a no-op (OperationNotPermitted)."""
    instance, mock_client = _make_instance(state="terminated")
    error = ClientError(
        {"Error": {"Code": "OperationNotPermitted", "Message": "instance is terminated"}},
        "TerminateInstances",
    )
    mock_client.terminate_instances.side_effect = error
    instance.delete()  # Should not raise
    mock_client.terminate_instances.assert_called_once()


def test_delete_not_found():
    """delete() on a non-existent instance is a no-op."""
    instance_id = "i-0abcdef1234567890"
    mock_client = mock.MagicMock()
    mock_client.terminate_instances.side_effect = _make_client_error("InvalidInstanceID.NotFound")

    instance = EC2Instance(instance_id=instance_id, ec2_client=mock_client)
    instance.delete()  # Should not raise
    mock_client.terminate_instances.assert_called_once()
