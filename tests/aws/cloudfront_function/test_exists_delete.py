"""Tests for CloudFrontFunction.exists and CloudFrontFunction.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.cloudfront_function import CloudFrontFunction

FUNCTION_NAME = "my-redirect-function"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_function_name():
    """function_name returns the name passed to the constructor."""
    fn = CloudFrontFunction(FUNCTION_NAME)
    assert fn.function_name == FUNCTION_NAME


def test_exists_true():
    """exists returns True when the function is found."""
    fn = CloudFrontFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_function.return_value = {
        "FunctionSummary": {"Name": FUNCTION_NAME},
        "ETag": "ETAG1",
    }

    with mock.patch.object(
        CloudFrontFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert fn.exists is True
        mock_client.describe_function.assert_called_once_with(Name=FUNCTION_NAME)


def test_exists_not_found():
    """exists returns False when NoSuchFunctionExists is raised."""
    fn = CloudFrontFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_function.side_effect = _make_client_error("NoSuchFunctionExists")

    with mock.patch.object(
        CloudFrontFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert fn.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    fn = CloudFrontFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_function.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(
        CloudFrontFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            _ = fn.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


def test_delete():
    """delete() fetches ETag then calls delete_function."""
    fn = CloudFrontFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_function.return_value = {
        "FunctionSummary": {"Name": FUNCTION_NAME},
        "ETag": "ETAG1",
    }

    with mock.patch.object(
        CloudFrontFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        fn.delete()

    mock_client.delete_function.assert_called_once_with(Name=FUNCTION_NAME, IfMatch="ETAG1")


def test_delete_not_found():
    """delete() on a non-existent function is a no-op."""
    fn = CloudFrontFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_function.side_effect = _make_client_error("NoSuchFunctionExists")

    with mock.patch.object(
        CloudFrontFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        fn.delete()  # Should not raise

    mock_client.delete_function.assert_not_called()


def test_delete_in_use():
    """delete() re-raises FunctionInUse."""
    fn = CloudFrontFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_function.return_value = {
        "FunctionSummary": {"Name": FUNCTION_NAME},
        "ETag": "ETAG1",
    }
    mock_client.delete_function.side_effect = _make_client_error("FunctionInUse")

    with mock.patch.object(
        CloudFrontFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            fn.delete()
        assert exc_info.value.response["Error"]["Code"] == "FunctionInUse"


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors during ETag fetch."""
    fn = CloudFrontFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_function.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(
        CloudFrontFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            fn.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
