"""Tests for VPCFlowLog.exists and VPCFlowLog.delete()."""

from unittest import mock

import pytest

from infrahouse_core.aws.vpc_flow_log import VPCFlowLog

FL_ID = "fl-0123456789abcdef0"


def test_flow_log_id():
    fl = VPCFlowLog(FL_ID)
    assert fl.flow_log_id == FL_ID


def test_exists_true():
    fl = VPCFlowLog(FL_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_flow_logs.return_value = {"FlowLogs": [{"FlowLogId": FL_ID}]}
    with mock.patch.object(VPCFlowLog, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert fl.exists is True
    mock_client.describe_flow_logs.assert_called_once_with(FlowLogIds=[FL_ID])


def test_exists_false():
    fl = VPCFlowLog(FL_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_flow_logs.return_value = {"FlowLogs": []}
    with mock.patch.object(VPCFlowLog, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert fl.exists is False


def test_delete():
    fl = VPCFlowLog(FL_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_flow_logs.return_value = {"Unsuccessful": []}
    with mock.patch.object(VPCFlowLog, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        fl.delete()
    mock_client.delete_flow_logs.assert_called_once_with(FlowLogIds=[FL_ID])


def test_delete_unsuccessful():
    fl = VPCFlowLog(FL_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_flow_logs.return_value = {
        "Unsuccessful": [{"Error": {"Code": "SomeError", "Message": "Something went wrong"}}]
    }
    with mock.patch.object(VPCFlowLog, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        fl.delete()  # Logs a warning but does not raise
