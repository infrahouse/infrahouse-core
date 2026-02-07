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
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"logGroups": [{"logGroupName": LOG_GROUP_NAME}]}]
    )

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
