"""Tests for Subnet.exists and Subnet.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.subnet import Subnet

SUBNET_ID = "subnet-0123456789abcdef0"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_subnet_id():
    subnet = Subnet(SUBNET_ID)
    assert subnet.subnet_id == SUBNET_ID


def test_exists_true():
    subnet = Subnet(SUBNET_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_subnets.return_value = {"Subnets": [{"SubnetId": SUBNET_ID}]}
    with mock.patch.object(Subnet, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert subnet.exists is True
    mock_client.describe_subnets.assert_called_once_with(SubnetIds=[SUBNET_ID])


def test_exists_false():
    subnet = Subnet(SUBNET_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_subnets.side_effect = _make_client_error("InvalidSubnetID.NotFound")
    with mock.patch.object(Subnet, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert subnet.exists is False


def test_delete():
    subnet = Subnet(SUBNET_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(Subnet, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        subnet.delete()
    mock_client.delete_subnet.assert_called_once_with(SubnetId=SUBNET_ID)


def test_delete_not_found():
    subnet = Subnet(SUBNET_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_subnet.side_effect = _make_client_error("InvalidSubnetID.NotFound")
    with mock.patch.object(Subnet, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        subnet.delete()  # Should not raise


def test_delete_unexpected_error():
    subnet = Subnet(SUBNET_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_subnet.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(Subnet, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            subnet.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
