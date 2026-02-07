"""Tests for SecurityGroup.exists and SecurityGroup.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.security_group import SecurityGroup

SG_ID = "sg-0123456789abcdef0"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


# -- group_id property --------------------------------------------------------


def test_group_id():
    """group_id returns the ID passed to the constructor."""
    sg = SecurityGroup(SG_ID)
    assert sg.group_id == SG_ID


# -- exists -------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the Security Group is found."""
    sg = SecurityGroup(SG_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_security_groups.return_value = {
        "SecurityGroups": [{"GroupId": SG_ID}]
    }

    with mock.patch.object(SecurityGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert sg.exists is True
        mock_client.describe_security_groups.assert_called_once_with(GroupIds=[SG_ID])


def test_exists_not_found():
    """exists returns False when InvalidGroup.NotFound is raised."""
    sg = SecurityGroup(SG_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_security_groups.side_effect = _make_client_error("InvalidGroup.NotFound")

    with mock.patch.object(SecurityGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert sg.exists is False


def test_exists_unexpected_error():
    """Unexpected errors from describe_security_groups are re-raised."""
    sg = SecurityGroup(SG_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_security_groups.side_effect = _make_client_error("UnauthorizedOperation")

    with mock.patch.object(SecurityGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = sg.exists
        assert exc_info.value.response["Error"]["Code"] == "UnauthorizedOperation"


# -- delete -------------------------------------------------------------------


def test_delete():
    """delete() calls delete_security_group with the correct ID."""
    sg = SecurityGroup(SG_ID, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(SecurityGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        sg.delete()

    mock_client.delete_security_group.assert_called_once_with(GroupId=SG_ID)


def test_delete_not_found():
    """delete() on a non-existent Security Group is a no-op."""
    sg = SecurityGroup(SG_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_security_group.side_effect = _make_client_error("InvalidGroup.NotFound")

    with mock.patch.object(SecurityGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        sg.delete()  # Should not raise


def test_delete_dependency_violation():
    """delete() propagates DependencyViolation -- caller must handle it."""
    sg = SecurityGroup(SG_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_security_group.side_effect = _make_client_error("DependencyViolation")

    with mock.patch.object(SecurityGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            sg.delete()
        assert exc_info.value.response["Error"]["Code"] == "DependencyViolation"


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    sg = SecurityGroup(SG_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_security_group.side_effect = _make_client_error("UnauthorizedOperation")

    with mock.patch.object(SecurityGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            sg.delete()
        assert exc_info.value.response["Error"]["Code"] == "UnauthorizedOperation"
