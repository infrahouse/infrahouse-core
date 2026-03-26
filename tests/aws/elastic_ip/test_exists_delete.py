"""Tests for ElasticIP.exists and ElasticIP.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.elastic_ip import ElasticIP

ALLOC_ID = "eipalloc-0123456789abcdef0"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_allocation_id():
    eip = ElasticIP(ALLOC_ID)
    assert eip.allocation_id == ALLOC_ID


def test_exists_true():
    eip = ElasticIP(ALLOC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_addresses.return_value = {"Addresses": [{"AllocationId": ALLOC_ID}]}
    with mock.patch.object(ElasticIP, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert eip.exists is True
    mock_client.describe_addresses.assert_called_once_with(AllocationIds=[ALLOC_ID])


def test_exists_false():
    eip = ElasticIP(ALLOC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_addresses.side_effect = _make_client_error("InvalidAddressID.NotFound")
    with mock.patch.object(ElasticIP, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert eip.exists is False


def test_delete():
    eip = ElasticIP(ALLOC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(ElasticIP, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        eip.delete()
    mock_client.release_address.assert_called_once_with(AllocationId=ALLOC_ID)


def test_delete_not_found():
    eip = ElasticIP(ALLOC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.release_address.side_effect = _make_client_error("InvalidAddressID.NotFound")
    with mock.patch.object(ElasticIP, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        eip.delete()  # Should not raise


def test_delete_unexpected_error():
    eip = ElasticIP(ALLOC_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.release_address.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(ElasticIP, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            eip.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
