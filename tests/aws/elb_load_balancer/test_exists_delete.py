"""Tests for ELBLoadBalancer.exists and ELBLoadBalancer.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.elb_load_balancer import ELBLoadBalancer

LB_ARN = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-lb/50dc6c495c0c9188"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


# -- load_balancer_arn property ------------------------------------------------


def test_load_balancer_arn():
    """load_balancer_arn returns the ARN passed to the constructor."""
    lb = ELBLoadBalancer(LB_ARN)
    assert lb.load_balancer_arn == LB_ARN


# -- exists -------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the load balancer is found."""
    lb = ELBLoadBalancer(LB_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_load_balancers.return_value = {
        "LoadBalancers": [{"LoadBalancerArn": LB_ARN}]
    }

    with mock.patch.object(ELBLoadBalancer, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lb.exists is True
        mock_client.describe_load_balancers.assert_called_once_with(LoadBalancerArns=[LB_ARN])


def test_exists_not_found():
    """exists returns False when LoadBalancerNotFoundException is raised."""
    lb = ELBLoadBalancer(LB_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_load_balancers.side_effect = _make_client_error("LoadBalancerNotFoundException")

    with mock.patch.object(ELBLoadBalancer, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lb.exists is False


def test_exists_unexpected_error():
    """Unexpected errors from describe_load_balancers are re-raised."""
    lb = ELBLoadBalancer(LB_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_load_balancers.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ELBLoadBalancer, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = lb.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# -- delete -------------------------------------------------------------------


def test_delete():
    """delete() calls delete_load_balancer with the correct ARN."""
    lb = ELBLoadBalancer(LB_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(ELBLoadBalancer, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        lb.delete()

    mock_client.delete_load_balancer.assert_called_once_with(LoadBalancerArn=LB_ARN)


def test_delete_not_found():
    """delete() on a non-existent load balancer is a no-op."""
    lb = ELBLoadBalancer(LB_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_load_balancer.side_effect = _make_client_error("LoadBalancerNotFoundException")

    with mock.patch.object(ELBLoadBalancer, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        lb.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    lb = ELBLoadBalancer(LB_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_load_balancer.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ELBLoadBalancer, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            lb.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
