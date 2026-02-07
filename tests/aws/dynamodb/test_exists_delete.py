"""Tests for DynamoDBTable.exists and DynamoDBTable.delete()."""

from unittest import mock

from botocore.exceptions import ClientError

from infrahouse_core.aws.dynamodb import DynamoDBTable


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def test_exists_true():
    """exists returns True when the table is found."""
    table = DynamoDBTable("my-table", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_table.return_value = {"Table": {"TableName": "my-table"}}

    with mock.patch.object(DynamoDBTable, "_dynamodb_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert table.exists is True
        mock_client.describe_table.assert_called_once_with(TableName="my-table")


def test_exists_false():
    """exists returns False when the table does not exist."""
    table = DynamoDBTable("my-table", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_table.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(DynamoDBTable, "_dynamodb_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert table.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    table = DynamoDBTable("my-table", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_table.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(DynamoDBTable, "_dynamodb_client", new_callable=mock.PropertyMock, return_value=mock_client):
        try:
            _ = table.exists
            assert False, "Should have raised ClientError"
        except ClientError as err:
            assert err.response["Error"]["Code"] == "AccessDeniedException"


def test_delete():
    """delete() calls delete_table."""
    table = DynamoDBTable("my-table", region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(DynamoDBTable, "_dynamodb_client", new_callable=mock.PropertyMock, return_value=mock_client):
        table.delete()
        mock_client.delete_table.assert_called_once_with(TableName="my-table")


def test_delete_not_exists():
    """delete() on a non-existent table is a no-op."""
    table = DynamoDBTable("my-table", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_table.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(DynamoDBTable, "_dynamodb_client", new_callable=mock.PropertyMock, return_value=mock_client):
        table.delete()  # Should not raise
        mock_client.delete_table.assert_called_once()


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    table = DynamoDBTable("my-table", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_table.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(DynamoDBTable, "_dynamodb_client", new_callable=mock.PropertyMock, return_value=mock_client):
        try:
            table.delete()
            assert False, "Should have raised ClientError"
        except ClientError as err:
            assert err.response["Error"]["Code"] == "AccessDeniedException"
