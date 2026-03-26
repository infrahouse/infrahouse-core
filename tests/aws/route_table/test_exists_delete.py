"""Tests for RouteTable.exists and RouteTable.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.route_table import RouteTable

RTB_ID = "rtb-0123456789abcdef0"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_route_table_id():
    rtb = RouteTable(RTB_ID)
    assert rtb.route_table_id == RTB_ID


def test_exists_true():
    rtb = RouteTable(RTB_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_route_tables.return_value = {"RouteTables": [{"RouteTableId": RTB_ID}]}
    with mock.patch.object(RouteTable, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert rtb.exists is True
    mock_client.describe_route_tables.assert_called_once_with(RouteTableIds=[RTB_ID])


def test_exists_false():
    rtb = RouteTable(RTB_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_route_tables.side_effect = _make_client_error("InvalidRouteTableID.NotFound")
    with mock.patch.object(RouteTable, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert rtb.exists is False


def test_delete():
    rtb = RouteTable(RTB_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(RouteTable, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        rtb.delete()
    mock_client.delete_route_table.assert_called_once_with(RouteTableId=RTB_ID)


def test_delete_not_found():
    rtb = RouteTable(RTB_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_route_table.side_effect = _make_client_error("InvalidRouteTableID.NotFound")
    with mock.patch.object(RouteTable, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        rtb.delete()  # Should not raise


def test_delete_unexpected_error():
    rtb = RouteTable(RTB_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_route_table.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(RouteTable, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            rtb.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
