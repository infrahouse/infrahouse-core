"""Tests for EventBridgeRule.exists and EventBridgeRule.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.eventbridge_rule import EventBridgeRule

RULE_NAME = "my-rule"
EVENT_BUS = "default"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


# -- properties ---------------------------------------------------------------


def test_rule_name():
    """rule_name returns the name passed to the constructor."""
    rule = EventBridgeRule(RULE_NAME)
    assert rule.rule_name == RULE_NAME


def test_event_bus_name_default():
    """event_bus_name defaults to 'default'."""
    rule = EventBridgeRule(RULE_NAME)
    assert rule.event_bus_name == "default"


def test_event_bus_name_custom():
    """event_bus_name returns the custom bus name."""
    rule = EventBridgeRule(RULE_NAME, event_bus_name="custom-bus")
    assert rule.event_bus_name == "custom-bus"


# -- exists -------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the rule is found."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_rule.return_value = {"Name": RULE_NAME}

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert rule.exists is True
        mock_client.describe_rule.assert_called_once_with(Name=RULE_NAME, EventBusName=EVENT_BUS)


def test_exists_not_found():
    """exists returns False when ResourceNotFoundException is raised."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_rule.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert rule.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_rule.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = rule.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# -- delete -------------------------------------------------------------------


def test_delete_no_targets():
    """delete() with no targets deletes the rule directly."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"Targets": []}])

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        rule.delete()

    mock_client.remove_targets.assert_not_called()
    mock_client.delete_rule.assert_called_once_with(Name=RULE_NAME, EventBusName=EVENT_BUS)


def test_delete_with_targets():
    """delete() removes targets before deleting the rule."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"Targets": [{"Id": "target-1", "Arn": "arn:1"}, {"Id": "target-2", "Arn": "arn:2"}]}]
    )

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        rule.delete()

    mock_client.remove_targets.assert_called_once_with(
        Rule=RULE_NAME,
        EventBusName=EVENT_BUS,
        Ids=["target-1", "target-2"],
    )
    mock_client.delete_rule.assert_called_once_with(Name=RULE_NAME, EventBusName=EVENT_BUS)


def test_delete_with_paginated_targets():
    """delete() handles multiple pages of targets."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [
            {"Targets": [{"Id": "target-1", "Arn": "arn:1"}]},
            {"Targets": [{"Id": "target-2", "Arn": "arn:2"}]},
        ]
    )

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        rule.delete()

    assert mock_client.remove_targets.call_count == 2
    mock_client.delete_rule.assert_called_once_with(Name=RULE_NAME, EventBusName=EVENT_BUS)


def test_delete_custom_event_bus():
    """delete() passes the custom event bus name."""
    rule = EventBridgeRule(RULE_NAME, event_bus_name="custom-bus", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"Targets": []}])

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        rule.delete()

    mock_client.delete_rule.assert_called_once_with(Name=RULE_NAME, EventBusName="custom-bus")


def test_delete_not_found():
    """delete() on a non-existent rule is a no-op."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"Targets": []}])
    mock_client.delete_rule.side_effect = _make_client_error("ResourceNotFoundException")

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        rule.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    rule = EventBridgeRule(RULE_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"Targets": []}])
    mock_client.delete_rule.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(EventBridgeRule, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            rule.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
