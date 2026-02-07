"""Tests for NATGateway.exists and NATGateway.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.nat_gateway import NATGateway

NAT_GW_ID = "nat-0123456789abcdef0"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


# -- nat_gateway_id property --------------------------------------------------


def test_nat_gateway_id():
    """nat_gateway_id returns the ID passed to the constructor."""
    gw = NATGateway(NAT_GW_ID)
    assert gw.nat_gateway_id == NAT_GW_ID


# -- exists -------------------------------------------------------------------


def test_exists_available():
    """exists returns True when the NAT Gateway is in 'available' state."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.return_value = {
        "NatGateways": [{"NatGatewayId": NAT_GW_ID, "State": "available"}]
    }

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert gw.exists is True
        mock_client.describe_nat_gateways.assert_called_once_with(NatGatewayIds=[NAT_GW_ID])


def test_exists_pending():
    """exists returns True when the NAT Gateway is in 'pending' state."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.return_value = {
        "NatGateways": [{"NatGatewayId": NAT_GW_ID, "State": "pending"}]
    }

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert gw.exists is True


def test_exists_failed():
    """exists returns True when the NAT Gateway is in 'failed' state (it still exists)."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.return_value = {
        "NatGateways": [{"NatGatewayId": NAT_GW_ID, "State": "failed"}]
    }

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert gw.exists is True


def test_exists_deleting():
    """exists returns False when the NAT Gateway is in 'deleting' state."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.return_value = {
        "NatGateways": [{"NatGatewayId": NAT_GW_ID, "State": "deleting"}]
    }

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert gw.exists is False


def test_exists_deleted():
    """exists returns False when the NAT Gateway is in 'deleted' state."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.return_value = {
        "NatGateways": [{"NatGatewayId": NAT_GW_ID, "State": "deleted"}]
    }

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert gw.exists is False


def test_exists_empty_response():
    """exists returns False when the API returns no NAT Gateways."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.return_value = {"NatGateways": []}

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert gw.exists is False


def test_exists_not_found():
    """exists returns False when NatGatewayNotFound is raised."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.side_effect = _make_client_error("NatGatewayNotFound")

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert gw.exists is False


def test_exists_unexpected_error():
    """Unexpected errors from describe_nat_gateways are re-raised."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_nat_gateways.side_effect = _make_client_error("UnauthorizedOperation")

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = gw.exists
        assert exc_info.value.response["Error"]["Code"] == "UnauthorizedOperation"


# -- delete -------------------------------------------------------------------


def test_delete():
    """delete() calls delete_nat_gateway with the correct ID."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        gw.delete()

    mock_client.delete_nat_gateway.assert_called_once_with(NatGatewayId=NAT_GW_ID)


def test_delete_not_found():
    """delete() on a non-existent NAT Gateway is a no-op."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_nat_gateway.side_effect = _make_client_error("NatGatewayNotFound")

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        gw.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    gw = NATGateway(NAT_GW_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_nat_gateway.side_effect = _make_client_error("UnauthorizedOperation")

    with mock.patch.object(NATGateway, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            gw.delete()
        assert exc_info.value.response["Error"]["Code"] == "UnauthorizedOperation"
