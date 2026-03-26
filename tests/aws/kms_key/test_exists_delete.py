"""Tests for KMSKey.exists and KMSKey.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.kms_key import KMSKey

KEY_ID = "1234abcd-12ab-34cd-56ef-1234567890ab"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_key_id():
    key = KMSKey(KEY_ID)
    assert key.key_id == KEY_ID


def test_exists_true():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_key.return_value = {"KeyMetadata": {"KeyState": "Enabled"}}
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert key.exists is True
    mock_client.describe_key.assert_called_once_with(KeyId=KEY_ID)


def test_exists_false_not_found():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_key.side_effect = _make_client_error("NotFoundException")
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert key.exists is False


def test_exists_false_pending_deletion():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_key.return_value = {"KeyMetadata": {"KeyState": "PendingDeletion"}}
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert key.exists is False


def test_delete():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        key.delete()
    mock_client.schedule_key_deletion.assert_called_once_with(KeyId=KEY_ID, PendingWindowInDays=7)


def test_delete_custom_window():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        key.delete(pending_window_in_days=30)
    mock_client.schedule_key_deletion.assert_called_once_with(KeyId=KEY_ID, PendingWindowInDays=30)


def test_delete_already_pending():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.schedule_key_deletion.side_effect = _make_client_error("KMSInvalidStateException")
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        key.delete()  # Should not raise


def test_delete_not_found():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.schedule_key_deletion.side_effect = _make_client_error("NotFoundException")
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        key.delete()  # Should not raise


def test_delete_unexpected_error():
    key = KMSKey(KEY_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.schedule_key_deletion.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(KMSKey, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            key.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
