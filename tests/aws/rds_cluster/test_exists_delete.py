"""Tests for RDSCluster.exists and RDSCluster.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.rds_cluster import RDSCluster

DB_CLUSTER_ID = "my-cluster"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_db_cluster_id():
    cluster = RDSCluster(DB_CLUSTER_ID)
    assert cluster.db_cluster_id == DB_CLUSTER_ID


def test_exists_true():
    cluster = RDSCluster(DB_CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_clusters.return_value = {"DBClusters": [{"DBClusterIdentifier": DB_CLUSTER_ID}]}
    with mock.patch.object(RDSCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert cluster.exists is True
    mock_client.describe_db_clusters.assert_called_once_with(DBClusterIdentifier=DB_CLUSTER_ID)


def test_exists_false():
    cluster = RDSCluster(DB_CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_clusters.side_effect = _make_client_error("DBClusterNotFoundFault")
    with mock.patch.object(RDSCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert cluster.exists is False


def test_delete():
    cluster = RDSCluster(DB_CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_clusters.return_value = {
        "DBClusters": [
            {
                "DBClusterIdentifier": DB_CLUSTER_ID,
                "DBClusterMembers": [
                    {"DBInstanceIdentifier": "member-1"},
                    {"DBInstanceIdentifier": "member-2"},
                ],
            }
        ]
    }
    with mock.patch.object(RDSCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        cluster.delete()

    # Should delete both member instances then the cluster
    assert mock_client.delete_db_instance.call_count == 2
    mock_client.delete_db_instance.assert_any_call(DBInstanceIdentifier="member-1", SkipFinalSnapshot=True)
    mock_client.delete_db_instance.assert_any_call(DBInstanceIdentifier="member-2", SkipFinalSnapshot=True)
    mock_client.delete_db_cluster.assert_called_once_with(DBClusterIdentifier=DB_CLUSTER_ID, SkipFinalSnapshot=True)


def test_delete_no_members():
    cluster = RDSCluster(DB_CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_clusters.return_value = {
        "DBClusters": [{"DBClusterIdentifier": DB_CLUSTER_ID, "DBClusterMembers": []}]
    }
    with mock.patch.object(RDSCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        cluster.delete()
    mock_client.delete_db_instance.assert_not_called()
    mock_client.delete_db_cluster.assert_called_once_with(DBClusterIdentifier=DB_CLUSTER_ID, SkipFinalSnapshot=True)


def test_delete_not_found():
    cluster = RDSCluster(DB_CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_clusters.side_effect = _make_client_error("DBClusterNotFoundFault")
    with mock.patch.object(RDSCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        cluster.delete()  # Should not raise
    mock_client.delete_db_cluster.assert_not_called()


def test_delete_unexpected_error():
    cluster = RDSCluster(DB_CLUSTER_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_clusters.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(RDSCluster, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            cluster.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
