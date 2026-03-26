"""Tests for InternetGateway.exists and InternetGateway.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.internet_gateway import InternetGateway

IGW_ID = "igw-0123456789abcdef0"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_igw_id():
    igw = InternetGateway(IGW_ID)
    assert igw.igw_id == IGW_ID


def test_exists_true():
    igw = InternetGateway(IGW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_internet_gateways.return_value = {"InternetGateways": [{"InternetGatewayId": IGW_ID}]}
    with mock.patch.object(InternetGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert igw.exists is True
    mock_client.describe_internet_gateways.assert_called_once_with(InternetGatewayIds=[IGW_ID])


def test_exists_false():
    igw = InternetGateway(IGW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_internet_gateways.side_effect = _make_client_error("InvalidInternetGatewayID.NotFound")
    with mock.patch.object(InternetGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert igw.exists is False


def test_delete():
    igw = InternetGateway(IGW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_internet_gateways.return_value = {
        "InternetGateways": [{"InternetGatewayId": IGW_ID, "Attachments": []}]
    }
    with mock.patch.object(InternetGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        igw.delete()
    mock_client.delete_internet_gateway.assert_called_once_with(InternetGatewayId=IGW_ID)
    mock_client.detach_internet_gateway.assert_not_called()


def test_delete_detaches_from_vpc():
    igw = InternetGateway(IGW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_internet_gateways.return_value = {
        "InternetGateways": [
            {
                "InternetGatewayId": IGW_ID,
                "Attachments": [{"VpcId": "vpc-aaa"}, {"VpcId": "vpc-bbb"}],
            }
        ]
    }
    with mock.patch.object(InternetGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        igw.delete()
    assert mock_client.detach_internet_gateway.call_count == 2
    mock_client.detach_internet_gateway.assert_any_call(InternetGatewayId=IGW_ID, VpcId="vpc-aaa")
    mock_client.detach_internet_gateway.assert_any_call(InternetGatewayId=IGW_ID, VpcId="vpc-bbb")
    mock_client.delete_internet_gateway.assert_called_once_with(InternetGatewayId=IGW_ID)


def test_delete_not_found():
    igw = InternetGateway(IGW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_internet_gateways.side_effect = _make_client_error("InvalidInternetGatewayID.NotFound")
    with mock.patch.object(InternetGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        igw.delete()  # Should not raise
    mock_client.delete_internet_gateway.assert_not_called()


def test_delete_unexpected_error():
    igw = InternetGateway(IGW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_internet_gateways.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(InternetGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            igw.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
