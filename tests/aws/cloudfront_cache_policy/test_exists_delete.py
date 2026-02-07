"""Tests for CloudFrontCachePolicy.exists and CloudFrontCachePolicy.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.cloudfront_cache_policy import CloudFrontCachePolicy

POLICY_ID = "658327ea-f89d-4fab-a63d-7e88639e58f6"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_policy_id():
    """policy_id returns the ID passed to the constructor."""
    policy = CloudFrontCachePolicy(POLICY_ID)
    assert policy.policy_id == POLICY_ID


def test_exists_true():
    """exists returns True when the cache policy is found."""
    policy = CloudFrontCachePolicy(POLICY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_cache_policy.return_value = {
        "CachePolicy": {"Id": POLICY_ID},
        "ETag": "ETAG1",
    }

    with mock.patch.object(
        CloudFrontCachePolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert policy.exists is True
        mock_client.get_cache_policy.assert_called_once_with(Id=POLICY_ID)


def test_exists_not_found():
    """exists returns False when NoSuchCachePolicy is raised."""
    policy = CloudFrontCachePolicy(POLICY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_cache_policy.side_effect = _make_client_error("NoSuchCachePolicy")

    with mock.patch.object(
        CloudFrontCachePolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert policy.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    policy = CloudFrontCachePolicy(POLICY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_cache_policy.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(
        CloudFrontCachePolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            _ = policy.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


def test_delete():
    """delete() fetches ETag then calls delete_cache_policy."""
    policy = CloudFrontCachePolicy(POLICY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_cache_policy.return_value = {
        "CachePolicy": {"Id": POLICY_ID},
        "ETag": "ETAG1",
    }

    with mock.patch.object(
        CloudFrontCachePolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        policy.delete()

    mock_client.delete_cache_policy.assert_called_once_with(Id=POLICY_ID, IfMatch="ETAG1")


def test_delete_not_found():
    """delete() on a non-existent cache policy is a no-op."""
    policy = CloudFrontCachePolicy(POLICY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_cache_policy.side_effect = _make_client_error("NoSuchCachePolicy")

    with mock.patch.object(
        CloudFrontCachePolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        policy.delete()  # Should not raise

    mock_client.delete_cache_policy.assert_not_called()


def test_delete_in_use():
    """delete() re-raises CachePolicyInUse."""
    policy = CloudFrontCachePolicy(POLICY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_cache_policy.return_value = {
        "CachePolicy": {"Id": POLICY_ID},
        "ETag": "ETAG1",
    }
    mock_client.delete_cache_policy.side_effect = _make_client_error("CachePolicyInUse")

    with mock.patch.object(
        CloudFrontCachePolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            policy.delete()
        assert exc_info.value.response["Error"]["Code"] == "CachePolicyInUse"


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors during ETag fetch."""
    policy = CloudFrontCachePolicy(POLICY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_cache_policy.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(
        CloudFrontCachePolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            policy.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
