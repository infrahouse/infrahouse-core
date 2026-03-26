"""Tests for RDSInstance.exists and RDSInstance.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.rds_instance import RDSInstance

DB_INSTANCE_ID = "my-database"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_db_instance_id():
    instance = RDSInstance(DB_INSTANCE_ID)
    assert instance.db_instance_id == DB_INSTANCE_ID


def test_exists_true():
    instance = RDSInstance(DB_INSTANCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_instances.return_value = {"DBInstances": [{"DBInstanceIdentifier": DB_INSTANCE_ID}]}
    with mock.patch.object(RDSInstance, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert instance.exists is True
    mock_client.describe_db_instances.assert_called_once_with(DBInstanceIdentifier=DB_INSTANCE_ID)


def test_exists_false():
    instance = RDSInstance(DB_INSTANCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_db_instances.side_effect = _make_client_error("DBInstanceNotFound")
    with mock.patch.object(RDSInstance, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert instance.exists is False


def test_delete():
    instance = RDSInstance(DB_INSTANCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(RDSInstance, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        instance.delete()
    mock_client.delete_db_instance.assert_called_once_with(DBInstanceIdentifier=DB_INSTANCE_ID, SkipFinalSnapshot=True)


def test_delete_not_found():
    instance = RDSInstance(DB_INSTANCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_db_instance.side_effect = _make_client_error("DBInstanceNotFound")
    with mock.patch.object(RDSInstance, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        instance.delete()  # Should not raise


def test_delete_unexpected_error():
    instance = RDSInstance(DB_INSTANCE_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_db_instance.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(RDSInstance, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            instance.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
