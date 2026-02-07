"""Tests for LambdaFunction.exists and LambdaFunction.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.lambda_function import LambdaFunction

FUNCTION_NAME = "my-function"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_function_name():
    """function_name returns the name passed to the constructor."""
    fn = LambdaFunction(FUNCTION_NAME)
    assert fn.function_name == FUNCTION_NAME


def test_exists_true():
    """exists returns True when the function is found."""
    fn = LambdaFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_function.return_value = {"Configuration": {"FunctionName": FUNCTION_NAME}}

    with mock.patch.object(LambdaFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert fn.exists is True
        mock_client.get_function.assert_called_once_with(FunctionName=FUNCTION_NAME)


def test_exists_not_found():
    """exists returns False when ResourceNotFoundException is raised."""
    fn = LambdaFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_function.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(LambdaFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert fn.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    fn = LambdaFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_function.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(LambdaFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = fn.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


def test_delete():
    """delete() calls delete_function with the correct name."""
    fn = LambdaFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(LambdaFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        fn.delete()

    mock_client.delete_function.assert_called_once_with(FunctionName=FUNCTION_NAME)


def test_delete_not_found():
    """delete() on a non-existent function is a no-op."""
    fn = LambdaFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_function.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(LambdaFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        fn.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    fn = LambdaFunction(FUNCTION_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_function.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(LambdaFunction, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            fn.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
