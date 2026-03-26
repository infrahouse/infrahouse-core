"""Tests for ElastiCacheCluster.exists and ElastiCacheCluster.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.elasticache_cluster import ElastiCacheCluster

CLUSTER_ID = "my-cache-cluster"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_cluster_id():
    cluster = ElastiCacheCluster(CLUSTER_ID)
    assert cluster.cluster_id == CLUSTER_ID


def test_exists_true():
    cluster = ElastiCacheCluster(CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_cache_clusters.return_value = {"CacheClusters": [{"CacheClusterId": CLUSTER_ID}]}
    with mock.patch.object(ElastiCacheCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert cluster.exists is True
    mock_client.describe_cache_clusters.assert_called_once_with(CacheClusterId=CLUSTER_ID)


def test_exists_false():
    cluster = ElastiCacheCluster(CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_cache_clusters.side_effect = _make_client_error("CacheClusterNotFound")
    with mock.patch.object(ElastiCacheCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert cluster.exists is False


def test_delete():
    cluster = ElastiCacheCluster(CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(ElastiCacheCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        cluster.delete()
    mock_client.delete_cache_cluster.assert_called_once_with(CacheClusterId=CLUSTER_ID)


def test_delete_not_found():
    cluster = ElastiCacheCluster(CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_cache_cluster.side_effect = _make_client_error("CacheClusterNotFound")
    with mock.patch.object(ElastiCacheCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        cluster.delete()  # Should not raise


def test_delete_unexpected_error():
    cluster = ElastiCacheCluster(CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_cache_cluster.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(ElastiCacheCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            cluster.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
