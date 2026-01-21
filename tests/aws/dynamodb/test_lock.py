from unittest import mock

import boto3
import pytest

from infrahouse_core.aws.dynamodb import DynamoDBTable


def _has_aws_credentials():
    """Check if AWS credentials are available."""
    try:
        credentials = boto3.Session().get_credentials()
        return credentials is not None
    except Exception:
        return False


def test_lock():
    t = DynamoDBTable("foo-table")
    with (
        mock.patch.object(DynamoDBTable, "put_item") as mock_put,
        mock.patch.object(DynamoDBTable, "delete_item") as mock_delete,
    ):
        with t.lock("foo"):
            print("hello")

        mock_put.assert_called_once()
        call_kwargs = mock_put.call_args[1]
        assert call_kwargs["Item"]["ResourceId"] == "foo"
        assert "expires_at" in call_kwargs["Item"]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(#r) OR #e < :now"
        assert call_kwargs["ExpressionAttributeNames"] == {"#r": "ResourceId", "#e": "expires_at"}
        assert ":now" in call_kwargs["ExpressionAttributeValues"]
        mock_delete.assert_called_once_with(Key={"ResourceId": "foo"})


def test_lock_custom_key_name():
    """Test lock() with a custom partition key name."""
    t = DynamoDBTable("foo-table")
    with (
        mock.patch.object(DynamoDBTable, "put_item") as mock_put,
        mock.patch.object(DynamoDBTable, "delete_item") as mock_delete,
    ):
        with t.lock("my-lock", key_name="pk"):
            print("hello")

        mock_put.assert_called_once()
        call_kwargs = mock_put.call_args[1]
        assert call_kwargs["Item"]["pk"] == "my-lock"
        assert "expires_at" in call_kwargs["Item"]
        mock_delete.assert_called_once_with(Key={"pk": "my-lock"})


def test_lock_without_ttl():
    """Test lock() with TTL disabled (ttl=None)."""
    t = DynamoDBTable("foo-table")
    with (
        mock.patch.object(DynamoDBTable, "put_item") as mock_put,
        mock.patch.object(DynamoDBTable, "delete_item") as mock_delete,
    ):
        with t.lock("foo", ttl=None):
            print("hello")

        mock_put.assert_called_once_with(
            Item={"ResourceId": "foo"},
            ConditionExpression="attribute_not_exists(#r)",
            ExpressionAttributeNames={"#r": "ResourceId"},
        )
        mock_delete.assert_called_once_with(Key={"ResourceId": "foo"})


@pytest.mark.skipif(not _has_aws_credentials(), reason="AWS credentials not available")
def test_non_expired_lock_blocks(dynamodb_table):
    """
    Integration test: a non-expired lock blocks new acquisitions.

    This verifies that TTL only allows stealing expired locks, not active ones.
    See: https://github.com/infrahouse/infrahouse-core/issues/81
    """
    from time import time

    table_name, region = dynamodb_table
    t = DynamoDBTable(table_name, region=region)

    # Create a lock that won't expire for another hour
    t.put_item(Item={"ResourceId": "active-lock", "expires_at": int(time()) + 3600})

    # Should NOT be able to steal a non-expired lock
    with pytest.raises(RuntimeError, match="Failed to acquire lock 'active-lock' after 2 seconds"):
        with t.lock("active-lock", timeout=2, ttl=300):
            pass


@pytest.mark.skipif(not _has_aws_credentials(), reason="AWS credentials not available")
def test_expired_lock_can_be_acquired(dynamodb_table):
    """
    Integration test: an expired lock can be acquired by a new process.

    This verifies the fix for issue #81 - if a Lambda crashes while holding a lock,
    other processes can acquire it after the TTL expires.
    See: https://github.com/infrahouse/infrahouse-core/issues/81
    """
    from time import time

    table_name, region = dynamodb_table
    t = DynamoDBTable(table_name, region=region)

    # Simulate a crashed process: create lock that expired 60 seconds ago
    t.put_item(Item={"ResourceId": "stale-lock", "expires_at": int(time()) - 60})

    # Should be able to acquire the expired lock immediately
    acquired = False
    with t.lock("stale-lock", timeout=5, ttl=300):
        acquired = True

    assert acquired, "Should have acquired the expired lock"
