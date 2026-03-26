"""Tests for OpenSearchDomain.exists and OpenSearchDomain.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.opensearch_domain import OpenSearchDomain

DOMAIN_NAME = "my-search-domain"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_domain_name():
    domain = OpenSearchDomain(DOMAIN_NAME)
    assert domain.domain_name == DOMAIN_NAME


def test_exists_true():
    domain = OpenSearchDomain(DOMAIN_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_domain.return_value = {"DomainStatus": {"DomainName": DOMAIN_NAME, "Deleted": False}}
    with mock.patch.object(OpenSearchDomain, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert domain.exists is True
    mock_client.describe_domain.assert_called_once_with(DomainName=DOMAIN_NAME)


def test_exists_false_not_found():
    domain = OpenSearchDomain(DOMAIN_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_domain.side_effect = _make_client_error("ResourceNotFoundException")
    with mock.patch.object(OpenSearchDomain, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert domain.exists is False


def test_exists_false_deleted():
    domain = OpenSearchDomain(DOMAIN_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_domain.return_value = {"DomainStatus": {"DomainName": DOMAIN_NAME, "Deleted": True}}
    with mock.patch.object(OpenSearchDomain, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert domain.exists is False


def test_delete():
    domain = OpenSearchDomain(DOMAIN_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(OpenSearchDomain, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        domain.delete()
    mock_client.delete_domain.assert_called_once_with(DomainName=DOMAIN_NAME)


def test_delete_not_found():
    domain = OpenSearchDomain(DOMAIN_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_domain.side_effect = _make_client_error("ResourceNotFoundException")
    with mock.patch.object(OpenSearchDomain, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        domain.delete()  # Should not raise


def test_delete_unexpected_error():
    domain = OpenSearchDomain(DOMAIN_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_domain.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(OpenSearchDomain, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            domain.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
