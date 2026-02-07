"""Tests for SQSQueue.exists and SQSQueue.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.sqs_queue import SQSQueue

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/my-queue"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_queue_url():
    """queue_url returns the URL passed to the constructor."""
    queue = SQSQueue(QUEUE_URL)
    assert queue.queue_url == QUEUE_URL


def test_exists_true():
    """exists returns True when the queue is found."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_queue_attributes.return_value = {
        "Attributes": {"QueueArn": "arn:aws:sqs:us-east-1:123456789012:my-queue"}
    }

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert queue.exists is True
        mock_client.get_queue_attributes.assert_called_once_with(
            QueueUrl=QUEUE_URL,
            AttributeNames=["QueueArn"],
        )


def test_exists_queue_does_not_exist():
    """exists returns False when QueueDoesNotExist is raised."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_queue_attributes.side_effect = _make_client_error("QueueDoesNotExist")

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert queue.exists is False


def test_exists_non_existent_queue():
    """exists returns False when NonExistentQueue is raised."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_queue_attributes.side_effect = _make_client_error("NonExistentQueue")

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert queue.exists is False


def test_exists_aws_non_existent_queue():
    """exists returns False when AWS.SimpleQueueService.NonExistentQueue is raised."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_queue_attributes.side_effect = _make_client_error(
        "AWS.SimpleQueueService.NonExistentQueue"
    )

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert queue.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_queue_attributes.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = queue.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


def test_delete():
    """delete() calls delete_queue with the correct URL."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        queue.delete()

    mock_client.delete_queue.assert_called_once_with(QueueUrl=QUEUE_URL)


def test_delete_not_found():
    """delete() on a non-existent queue is a no-op."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_queue.side_effect = _make_client_error("QueueDoesNotExist")

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        queue.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    queue = SQSQueue(QUEUE_URL, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_queue.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(SQSQueue, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            queue.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
