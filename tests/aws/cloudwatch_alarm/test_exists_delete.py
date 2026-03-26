"""Tests for CloudWatchAlarm.exists and CloudWatchAlarm.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.cloudwatch_alarm import CloudWatchAlarm

ALARM_NAME = "my-cpu-alarm"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def test_alarm_name():
    alarm = CloudWatchAlarm(ALARM_NAME)
    assert alarm.alarm_name == ALARM_NAME


def test_exists_true():
    alarm = CloudWatchAlarm(ALARM_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_alarms.return_value = {
        "MetricAlarms": [{"AlarmName": ALARM_NAME}],
        "CompositeAlarms": [],
    }
    with mock.patch.object(CloudWatchAlarm, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert alarm.exists is True
    mock_client.describe_alarms.assert_called_once_with(AlarmNames=[ALARM_NAME])


def test_exists_true_composite():
    alarm = CloudWatchAlarm(ALARM_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_alarms.return_value = {
        "MetricAlarms": [],
        "CompositeAlarms": [{"AlarmName": ALARM_NAME}],
    }
    with mock.patch.object(CloudWatchAlarm, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert alarm.exists is True


def test_exists_false():
    alarm = CloudWatchAlarm(ALARM_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_alarms.return_value = {
        "MetricAlarms": [],
        "CompositeAlarms": [],
    }
    with mock.patch.object(CloudWatchAlarm, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert alarm.exists is False


def test_delete():
    alarm = CloudWatchAlarm(ALARM_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(CloudWatchAlarm, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        alarm.delete()
    mock_client.delete_alarms.assert_called_once_with(AlarmNames=[ALARM_NAME])


def test_delete_unexpected_error():
    alarm = CloudWatchAlarm(ALARM_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_alarms.side_effect = _make_client_error("AccessDeniedException")
    with mock.patch.object(CloudWatchAlarm, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            alarm.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
