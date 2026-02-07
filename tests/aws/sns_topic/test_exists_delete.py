"""Tests for SNSTopic.exists and SNSTopic.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.sns_topic import SNSTopic

TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:my-topic"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_topic_arn():
    """topic_arn returns the ARN passed to the constructor."""
    topic = SNSTopic(TOPIC_ARN)
    assert topic.topic_arn == TOPIC_ARN


def test_exists_true():
    """exists returns True when the topic is found."""
    topic = SNSTopic(TOPIC_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_topic_attributes.return_value = {"Attributes": {"TopicArn": TOPIC_ARN}}

    with mock.patch.object(SNSTopic, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert topic.exists is True
        mock_client.get_topic_attributes.assert_called_once_with(TopicArn=TOPIC_ARN)


def test_exists_not_found():
    """exists returns False when NotFoundException is raised."""
    topic = SNSTopic(TOPIC_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_topic_attributes.side_effect = _make_client_error("NotFoundException")

    with mock.patch.object(SNSTopic, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert topic.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    topic = SNSTopic(TOPIC_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_topic_attributes.side_effect = _make_client_error("AuthorizationError")

    with mock.patch.object(SNSTopic, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = topic.exists
        assert exc_info.value.response["Error"]["Code"] == "AuthorizationError"


def test_delete():
    """delete() calls delete_topic with the correct ARN."""
    topic = SNSTopic(TOPIC_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(SNSTopic, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        topic.delete()

    mock_client.delete_topic.assert_called_once_with(TopicArn=TOPIC_ARN)


def test_delete_idempotent():
    """delete() does not raise even if topic doesn't exist (SNS is inherently idempotent)."""
    topic = SNSTopic(TOPIC_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    # SNS delete_topic doesn't raise for missing topics, so no side_effect needed

    with mock.patch.object(SNSTopic, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        topic.delete()  # Should not raise
