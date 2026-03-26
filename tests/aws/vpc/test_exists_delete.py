"""Tests for VPC.exists and VPC.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.vpc import VPC
from infrahouse_core.aws.vpc_endpoint import VPCEndpoint
from infrahouse_core.aws.vpc_flow_log import VPCFlowLog

VPC_ID = "vpc-0123456789abcdef0"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_vpc_id():
    vpc = VPC(VPC_ID)
    assert vpc.vpc_id == VPC_ID


def test_exists_true():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_vpcs.return_value = {"Vpcs": [{"VpcId": VPC_ID}]}
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert vpc.exists is True
    mock_client.describe_vpcs.assert_called_once_with(VpcIds=[VPC_ID])


def test_exists_false():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_vpcs.side_effect = _make_client_error("InvalidVpcID.NotFound")
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert vpc.exists is False


def test_delete():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        vpc.delete()
    mock_client.delete_vpc.assert_called_once_with(VpcId=VPC_ID)


def test_delete_not_found():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_vpc.side_effect = _make_client_error("InvalidVpcID.NotFound")
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        vpc.delete()  # Should not raise


def test_delete_unexpected_error():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_vpc.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            vpc.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


def test_vpc_endpoints():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_paginator = mock.MagicMock()
    mock_paginator.paginate.return_value = [
        {
            "VpcEndpoints": [
                {"VpcEndpointId": "vpce-aaa"},
                {"VpcEndpointId": "vpce-bbb"},
            ]
        }
    ]
    mock_client.get_paginator.return_value = mock_paginator
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        endpoints = vpc.vpc_endpoints
    assert len(endpoints) == 2
    assert all(isinstance(ep, VPCEndpoint) for ep in endpoints)
    assert endpoints[0].vpc_endpoint_id == "vpce-aaa"
    assert endpoints[1].vpc_endpoint_id == "vpce-bbb"
    mock_client.get_paginator.assert_called_once_with("describe_vpc_endpoints")


def test_vpc_endpoints_empty():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_paginator = mock.MagicMock()
    mock_paginator.paginate.return_value = [{"VpcEndpoints": []}]
    mock_client.get_paginator.return_value = mock_paginator
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        endpoints = vpc.vpc_endpoints
    assert endpoints == []


def test_flow_logs():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_paginator = mock.MagicMock()
    mock_paginator.paginate.return_value = [
        {
            "FlowLogs": [
                {"FlowLogId": "fl-aaa"},
                {"FlowLogId": "fl-bbb"},
            ]
        }
    ]
    mock_client.get_paginator.return_value = mock_paginator
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        fls = vpc.flow_logs
    assert len(fls) == 2
    assert all(isinstance(fl, VPCFlowLog) for fl in fls)
    assert fls[0].flow_log_id == "fl-aaa"
    assert fls[1].flow_log_id == "fl-bbb"
    mock_client.get_paginator.assert_called_once_with("describe_flow_logs")


def test_flow_logs_empty():
    vpc = VPC(VPC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_paginator = mock.MagicMock()
    mock_paginator.paginate.return_value = [{"FlowLogs": []}]
    mock_client.get_paginator.return_value = mock_paginator
    with mock.patch.object(VPC, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        fls = vpc.flow_logs
    assert fls == []
