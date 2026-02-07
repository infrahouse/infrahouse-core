"""Tests for ACMCertificate.exists and ACMCertificate.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.acm_certificate import ACMCertificate

CERT_ARN = "arn:aws:acm:us-east-1:123456789012:certificate/abc-123"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_certificate_arn():
    """certificate_arn returns the ARN passed to the constructor."""
    cert = ACMCertificate(CERT_ARN)
    assert cert.certificate_arn == CERT_ARN


def test_exists_true():
    """exists returns True when the certificate is found."""
    cert = ACMCertificate(CERT_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_certificate.return_value = {
        "Certificate": {"CertificateArn": CERT_ARN}
    }

    with mock.patch.object(ACMCertificate, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert cert.exists is True
        mock_client.describe_certificate.assert_called_once_with(CertificateArn=CERT_ARN)


def test_exists_not_found():
    """exists returns False when ResourceNotFoundException is raised."""
    cert = ACMCertificate(CERT_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_certificate.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(ACMCertificate, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert cert.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    cert = ACMCertificate(CERT_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_certificate.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ACMCertificate, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = cert.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


def test_delete():
    """delete() calls delete_certificate with the correct ARN."""
    cert = ACMCertificate(CERT_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(ACMCertificate, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        cert.delete()

    mock_client.delete_certificate.assert_called_once_with(CertificateArn=CERT_ARN)


def test_delete_not_found():
    """delete() on a non-existent certificate is a no-op."""
    cert = ACMCertificate(CERT_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_certificate.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(ACMCertificate, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        cert.delete()  # Should not raise


def test_delete_in_use():
    """delete() re-raises ResourceInUseException."""
    cert = ACMCertificate(CERT_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_certificate.side_effect = _make_client_error("ResourceInUseException")

    with mock.patch.object(ACMCertificate, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            cert.delete()
        assert exc_info.value.response["Error"]["Code"] == "ResourceInUseException"


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    cert = ACMCertificate(CERT_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_certificate.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ACMCertificate, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            cert.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
