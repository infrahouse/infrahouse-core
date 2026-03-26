"""Tests for CloudWatchLogGroup.exists and CloudWatchLogGroup.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.cloudwatch_log_group import CloudWatchLogGroup

LOG_GROUP_NAME = "/aws/lambda/my-function"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


# -- log_group_name property ---------------------------------------------------


def test_log_group_name():
    """log_group_name returns the name passed to the constructor."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME)
    assert lg.log_group_name == LOG_GROUP_NAME


# -- exists -------------------------------------------------------------------


def test_exists_true():
    """exists returns True when an exact match is found."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"logGroups": [{"logGroupName": LOG_GROUP_NAME}]}])

    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lg.exists is True


def test_exists_false_no_results():
    """exists returns False when no log groups are returned."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"logGroups": []}])

    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lg.exists is False


def test_exists_false_prefix_mismatch():
    """exists returns False when only a prefix match is found (not exact)."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    # The prefix search returns a longer name — not an exact match
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"logGroups": [{"logGroupName": LOG_GROUP_NAME + "-extra"}]}]
    )

    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lg.exists is False


def test_exists_exact_match_among_prefix_matches():
    """exists returns True when the exact match is among prefix matches."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [
            {
                "logGroups": [
                    {"logGroupName": LOG_GROUP_NAME + "-extra"},
                    {"logGroupName": LOG_GROUP_NAME},
                ]
            }
        ]
    )

    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lg.exists is True


# -- delete -------------------------------------------------------------------


def test_delete():
    """delete() calls delete_log_group with the correct name."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        lg.delete()

    mock_client.delete_log_group.assert_called_once_with(logGroupName=LOG_GROUP_NAME)


def test_delete_not_found():
    """delete() on a non-existent log group is a no-op."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_log_group.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        lg.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_log_group.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            lg.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# -- retention_in_days --------------------------------------------------------


def test_retention_in_days():
    """retention_in_days returns the value from describe_log_groups."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"logGroups": [{"logGroupName": LOG_GROUP_NAME, "retentionInDays": 365}]}]
    )
    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lg.retention_in_days == 365


def test_retention_in_days_never_expire():
    """retention_in_days returns None when retentionInDays is absent (never expire)."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"logGroups": [{"logGroupName": LOG_GROUP_NAME}]}])
    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert lg.retention_in_days is None


def test_retention_in_days_not_found():
    """retention_in_days raises ValueError when the log group does not exist."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"logGroups": []}])
    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ValueError, match="not found"):
            _ = lg.retention_in_days


# -- set_retention ------------------------------------------------------------


def test_set_retention():
    """set_retention calls put_retention_policy with correct args."""
    lg = CloudWatchLogGroup(LOG_GROUP_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    with mock.patch.object(CloudWatchLogGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        lg.set_retention(365)
    mock_client.put_retention_policy.assert_called_once_with(logGroupName=LOG_GROUP_NAME, retentionInDays=365)


# -- list_log_groups ----------------------------------------------------------


def test_list_log_groups():
    """list_log_groups returns CloudWatchLogGroup instances for all groups."""
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [
            {
                "logGroups": [
                    {"logGroupName": "/aws/lambda/func-a"},
                    {"logGroupName": "/aws/lambda/func-b"},
                ]
            }
        ]
    )
    with mock.patch("infrahouse_core.aws.cloudwatch_log_group.get_client", return_value=mock_client):
        groups = CloudWatchLogGroup.list_log_groups(region="us-east-1")
    assert len(groups) == 2
    assert all(isinstance(g, CloudWatchLogGroup) for g in groups)
    assert groups[0].log_group_name == "/aws/lambda/func-a"
    assert groups[1].log_group_name == "/aws/lambda/func-b"


def test_list_log_groups_with_prefix():
    """list_log_groups passes logGroupNamePrefix when prefix is given."""
    mock_client = mock.MagicMock()
    mock_paginator = mock.MagicMock()
    mock_paginator.paginate.return_value = [{"logGroups": []}]
    mock_client.get_paginator.return_value = mock_paginator
    with mock.patch("infrahouse_core.aws.cloudwatch_log_group.get_client", return_value=mock_client):
        CloudWatchLogGroup.list_log_groups(prefix="/aws/lambda/", region="us-east-1")
    mock_paginator.paginate.assert_called_once_with(logGroupNamePrefix="/aws/lambda/")


def test_list_log_groups_no_prefix():
    """list_log_groups does not pass logGroupNamePrefix when prefix is None."""
    mock_client = mock.MagicMock()
    mock_paginator = mock.MagicMock()
    mock_paginator.paginate.return_value = [{"logGroups": []}]
    mock_client.get_paginator.return_value = mock_paginator
    with mock.patch("infrahouse_core.aws.cloudwatch_log_group.get_client", return_value=mock_client):
        CloudWatchLogGroup.list_log_groups(region="us-east-1")
    mock_paginator.paginate.assert_called_once_with()
