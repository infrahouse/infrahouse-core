"""Tests for IAMGroup.exists, IAMGroup.delete(), and related properties/methods."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.iam_group import IAMGroup
from infrahouse_core.aws.iam_policy import IAMPolicy
from infrahouse_core.aws.iam_user import IAMUser


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


# -- group_name --------------------------------------------------------------


def test_group_name():
    """group_name returns the name passed to the constructor."""
    group = IAMGroup("admins")
    assert group.group_name == "admins"


# -- exists ------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the group is found."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_group.return_value = {"Group": {"GroupName": "admins"}, "Users": []}

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert group.exists is True
        mock_client.get_group.assert_called_once_with(GroupName="admins")


def test_exists_false():
    """exists returns False when the group does not exist."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_group.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert group.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_group.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = group.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- users -------------------------------------------------------------------


def test_users():
    """users returns IAMUser instances for each user in the group."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"Users": [{"UserName": "alice"}, {"UserName": "bob"}]}])

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = group.users

    assert len(result) == 2
    assert all(isinstance(u, IAMUser) for u in result)
    assert result[0].user_name == "alice"
    assert result[1].user_name == "bob"


def test_users_empty():
    """users returns an empty list when the group has no users."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"Users": []}])

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert group.users == []


# -- remove_user -------------------------------------------------------------


def test_remove_user():
    """remove_user removes the given user from the group."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    user = IAMUser("alice")

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        group.remove_user(user)

    mock_client.remove_user_from_group.assert_called_once_with(GroupName="admins", UserName="alice")


# -- managed_policies --------------------------------------------------------


def test_managed_policies():
    """managed_policies returns IAMPolicy instances."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123456789012:policy/pol-1"}]}]
    )

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = group.managed_policies

    assert len(result) == 1
    assert isinstance(result[0], IAMPolicy)
    assert result[0].policy_arn == "arn:aws:iam::123456789012:policy/pol-1"


# -- detach_policy -----------------------------------------------------------


def test_detach_policy():
    """detach_policy detaches the given policy from the group."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()
    policy = IAMPolicy("arn:aws:iam::123456789012:policy/pol-1")

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        group.detach_policy(policy)

    mock_client.detach_group_policy.assert_called_once_with(
        GroupName="admins", PolicyArn="arn:aws:iam::123456789012:policy/pol-1"
    )


# -- delete ------------------------------------------------------------------


def test_delete_full_teardown():
    """delete() detaches policies, removes users, then deletes."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator(
        [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123456789012:policy/pol-1"}]}]
    )
    inline_paginator = _mock_paginator([{"PolicyNames": ["inline-1"]}])
    users_paginator = _mock_paginator([{"Users": [{"UserName": "alice"}]}])

    paginators = iter([policies_paginator, inline_paginator, users_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        group.delete()

    # Managed policy detached
    mock_client.detach_group_policy.assert_called_once_with(
        GroupName="admins", PolicyArn="arn:aws:iam::123456789012:policy/pol-1"
    )
    # Inline policy deleted
    mock_client.delete_group_policy.assert_called_once_with(GroupName="admins", PolicyName="inline-1")
    # User removed from group
    mock_client.remove_user_from_group.assert_called_once_with(GroupName="admins", UserName="alice")
    # Group deleted
    mock_client.delete_group.assert_called_once_with(GroupName="admins")


def test_delete_no_dependencies():
    """delete() works when the group has no dependencies."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator([{"AttachedPolicies": []}])
    inline_paginator = _mock_paginator([{"PolicyNames": []}])
    users_paginator = _mock_paginator([{"Users": []}])

    paginators = iter([policies_paginator, inline_paginator, users_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        group.delete()

    mock_client.detach_group_policy.assert_not_called()
    mock_client.delete_group_policy.assert_not_called()
    mock_client.remove_user_from_group.assert_not_called()
    mock_client.delete_group.assert_called_once_with(GroupName="admins")


def test_delete_not_exists():
    """delete() on a non-existent group is a no-op."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator([{"AttachedPolicies": []}])
    inline_paginator = _mock_paginator([{"PolicyNames": []}])
    users_paginator = _mock_paginator([{"Users": []}])

    paginators = iter([policies_paginator, inline_paginator, users_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)
    mock_client.delete_group.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        group.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    group = IAMGroup("admins", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator([{"AttachedPolicies": []}])
    inline_paginator = _mock_paginator([{"PolicyNames": []}])
    users_paginator = _mock_paginator([{"Users": []}])

    paginators = iter([policies_paginator, inline_paginator, users_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)
    mock_client.delete_group.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            group.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
