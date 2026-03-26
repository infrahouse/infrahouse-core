"""Tests for VPCEndpoint.exists and VPCEndpoint.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.vpc_endpoint import VPCEndpoint

VPCE_ID = "vpce-0123456789abcdef0"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_vpc_endpoint_id():
    vpce = VPCEndpoint(VPCE_ID)
    assert vpce.vpc_endpoint_id == VPCE_ID


def test_exists_true():
    vpce = VPCEndpoint(VPCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_vpc_endpoints.return_value = {
        "VpcEndpoints": [{"VpcEndpointId": VPCE_ID, "State": "available"}]
    }
    with mock.patch.object(VPCEndpoint, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert vpce.exists is True
    mock_client.describe_vpc_endpoints.assert_called_once_with(VpcEndpointIds=[VPCE_ID])


def test_exists_false_not_found():
    vpce = VPCEndpoint(VPCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_vpc_endpoints.side_effect = _make_client_error("InvalidVpcEndpointId.NotFound")
    with mock.patch.object(VPCEndpoint, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert vpce.exists is False


def test_exists_false_deleted():
    vpce = VPCEndpoint(VPCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_vpc_endpoints.return_value = {"VpcEndpoints": [{"VpcEndpointId": VPCE_ID, "State": "deleted"}]}
    with mock.patch.object(VPCEndpoint, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert vpce.exists is False


def test_delete():
    vpce = VPCEndpoint(VPCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(VPCEndpoint, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        vpce.delete()
    mock_client.delete_vpc_endpoints.assert_called_once_with(VpcEndpointIds=[VPCE_ID])


def test_delete_not_found():
    vpce = VPCEndpoint(VPCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_vpc_endpoints.side_effect = _make_client_error("InvalidVpcEndpointId.NotFound")
    with mock.patch.object(VPCEndpoint, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        vpce.delete()  # Should not raise


def test_delete_unexpected_error():
    vpce = VPCEndpoint(VPCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_vpc_endpoints.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(VPCEndpoint, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            vpce.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
