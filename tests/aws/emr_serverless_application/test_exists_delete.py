"""Tests for EMRServerlessApplication.exists and EMRServerlessApplication.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.emr_serverless_application import EMRServerlessApplication

APP_ID = "00g2g3qttanqf409"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_application_id():
    app = EMRServerlessApplication(APP_ID)
    assert app.application_id == APP_ID


def test_exists_true():
    app = EMRServerlessApplication(APP_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_application.return_value = {"application": {"state": "CREATED"}}
    with mock.patch.object(
        EMRServerlessApplication, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert app.exists is True
    mock_client.get_application.assert_called_once_with(applicationId=APP_ID)


def test_exists_false_not_found():
    app = EMRServerlessApplication(APP_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_application.side_effect = _make_client_error("ResourceNotFoundException")
    with mock.patch.object(
        EMRServerlessApplication, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert app.exists is False


def test_exists_false_terminated():
    app = EMRServerlessApplication(APP_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_application.return_value = {"application": {"state": "TERMINATED"}}
    with mock.patch.object(
        EMRServerlessApplication, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert app.exists is False


def test_delete_stopped():
    app = EMRServerlessApplication(APP_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_application.return_value = {"application": {"state": "STOPPED"}}
    with mock.patch.object(
        EMRServerlessApplication, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        app.delete()
    mock_client.delete_application.assert_called_once_with(applicationId=APP_ID)
    mock_client.stop_application.assert_not_called()


def test_delete_not_found():
    app = EMRServerlessApplication(APP_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_application.side_effect = _make_client_error("ResourceNotFoundException")
    with mock.patch.object(
        EMRServerlessApplication, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        app.delete()  # Should not raise
    mock_client.delete_application.assert_not_called()


def test_delete_unexpected_error():
    app = EMRServerlessApplication(APP_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_application.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(
        EMRServerlessApplication, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            app.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
