from unittest import mock

import pytest

from infrahouse_core.aws.dynamodb import DynamoDBTable
from infrahouse_core.aws.exceptions import IHItemNotFound


def test_get_item_found():
    """Test get_item returns the item when it exists."""
    t = DynamoDBTable("foo-table")
    mock_table = mock.MagicMock()
    mock_table.get_item.return_value = {"Item": {"ResourceId": "test-key", "data": "test-value"}}

    with mock.patch.object(t, "_table", return_value=mock_table):
        result = t.get_item(Key={"ResourceId": "test-key"})

        mock_table.get_item.assert_called_once_with(Key={"ResourceId": "test-key"})
        assert result == {"ResourceId": "test-key", "data": "test-value"}


def test_get_item_not_found():
    """Test get_item raises IHItemNotFound when item does not exist."""
    t = DynamoDBTable("foo-table")
    mock_table = mock.MagicMock()
    mock_table.get_item.return_value = {}

    with mock.patch.object(t, "_table", return_value=mock_table):
        with pytest.raises(IHItemNotFound) as exc_info:
            t.get_item(Key={"ResourceId": "nonexistent-key"})

        mock_table.get_item.assert_called_once_with(Key={"ResourceId": "nonexistent-key"})
        assert "foo-table" in str(exc_info.value)
        assert "nonexistent-key" in str(exc_info.value)
