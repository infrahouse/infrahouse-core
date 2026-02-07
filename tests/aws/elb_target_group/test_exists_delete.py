"""Tests for ELBTargetGroup.exists and ELBTargetGroup.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.elb_target_group import ELBTargetGroup

TG_ARN = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/73e2d6bc24d8a067"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


# -- target_group_arn property -------------------------------------------------


def test_target_group_arn():
    """target_group_arn returns the ARN passed to the constructor."""
    tg = ELBTargetGroup(TG_ARN)
    assert tg.target_group_arn == TG_ARN


# -- exists -------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the target group is found."""
    tg = ELBTargetGroup(TG_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_target_groups.return_value = {
        "TargetGroups": [{"TargetGroupArn": TG_ARN}]
    }

    with mock.patch.object(ELBTargetGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert tg.exists is True
        mock_client.describe_target_groups.assert_called_once_with(TargetGroupArns=[TG_ARN])


def test_exists_not_found():
    """exists returns False when TargetGroupNotFoundException is raised."""
    tg = ELBTargetGroup(TG_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_target_groups.side_effect = _make_client_error("TargetGroupNotFoundException")

    with mock.patch.object(ELBTargetGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert tg.exists is False


def test_exists_unexpected_error():
    """Unexpected errors from describe_target_groups are re-raised."""
    tg = ELBTargetGroup(TG_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_target_groups.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ELBTargetGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = tg.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# -- delete -------------------------------------------------------------------


def test_delete():
    """delete() calls delete_target_group with the correct ARN."""
    tg = ELBTargetGroup(TG_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(ELBTargetGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        tg.delete()

    mock_client.delete_target_group.assert_called_once_with(TargetGroupArn=TG_ARN)


def test_delete_not_found():
    """delete() on a non-existent target group is a no-op."""
    tg = ELBTargetGroup(TG_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_target_group.side_effect = _make_client_error("TargetGroupNotFoundException")

    with mock.patch.object(ELBTargetGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        tg.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    tg = ELBTargetGroup(TG_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_target_group.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ELBTargetGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            tg.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
