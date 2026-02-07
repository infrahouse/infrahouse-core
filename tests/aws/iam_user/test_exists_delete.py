"""Tests for IAMUser.exists, IAMUser.delete(), and related properties/methods."""

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


# -- user_name ---------------------------------------------------------------


def test_user_name():
    """user_name returns the name passed to the constructor."""
    user = IAMUser("alice")
    assert user.user_name == "alice"


# -- exists ------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the user is found."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_user.return_value = {"User": {"UserName": "alice"}}

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert user.exists is True
        mock_client.get_user.assert_called_once_with(UserName="alice")


def test_exists_false():
    """exists returns False when the user does not exist."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_user.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert user.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_user.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = user.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- groups ------------------------------------------------------------------


def test_groups():
    """groups returns IAMGroup instances for each group the user belongs to."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"Groups": [{"GroupName": "admins"}, {"GroupName": "devs"}]}]
    )

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = user.groups

    assert len(result) == 2
    assert all(isinstance(g, IAMGroup) for g in result)
    assert result[0].group_name == "admins"
    assert result[1].group_name == "devs"


def test_groups_empty():
    """groups returns an empty list when the user is in no groups."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"Groups": []}])

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert user.groups == []


# -- managed_policies --------------------------------------------------------


def test_managed_policies():
    """managed_policies returns IAMPolicy instances."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123456789012:policy/pol-1"}]}]
    )

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = user.managed_policies

    assert len(result) == 1
    assert isinstance(result[0], IAMPolicy)
    assert result[0].policy_arn == "arn:aws:iam::123456789012:policy/pol-1"


# -- detach_policy -----------------------------------------------------------


def test_detach_policy():
    """detach_policy detaches the given policy from the user."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()
    policy = IAMPolicy("arn:aws:iam::123456789012:policy/pol-1")

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        user.detach_policy(policy)

    mock_client.detach_user_policy.assert_called_once_with(
        UserName="alice", PolicyArn="arn:aws:iam::123456789012:policy/pol-1"
    )


# -- delete ------------------------------------------------------------------


def test_delete_full_teardown():
    """delete() detaches policies, removes from groups, deletes keys, then deletes user."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator(
        [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123456789012:policy/pol-1"}]}]
    )
    inline_paginator = _mock_paginator([{"PolicyNames": ["inline-1"]}])
    groups_paginator = _mock_paginator([{"Groups": [{"GroupName": "admins"}]}])
    keys_paginator = _mock_paginator([{"AccessKeyMetadata": [{"AccessKeyId": "AKIA12345"}]}])

    # For _remove_from_groups, the IAMGroup.remove_user() call needs its own client.
    # We mock at the IAMUser level, but group.remove_user(self) will call group._client.
    # Since group is created inside _remove_from_groups via self.groups, we need to also
    # mock IAMGroup._client. We'll use a side_effect on get_paginator to serve all paginators.
    group_mock_client = mock.MagicMock()

    paginators = iter([policies_paginator, inline_paginator, groups_paginator, keys_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=group_mock_client):
            user.delete()

    # Managed policy detached
    mock_client.detach_user_policy.assert_called_once_with(
        UserName="alice", PolicyArn="arn:aws:iam::123456789012:policy/pol-1"
    )
    # Inline policy deleted
    mock_client.delete_user_policy.assert_called_once_with(UserName="alice", PolicyName="inline-1")
    # User removed from group via IAMGroup.remove_user()
    group_mock_client.remove_user_from_group.assert_called_once_with(GroupName="admins", UserName="alice")
    # Access key deleted
    mock_client.delete_access_key.assert_called_once_with(UserName="alice", AccessKeyId="AKIA12345")
    # User deleted
    mock_client.delete_user.assert_called_once_with(UserName="alice")


def test_delete_no_dependencies():
    """delete() works when the user has no dependencies."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator([{"AttachedPolicies": []}])
    inline_paginator = _mock_paginator([{"PolicyNames": []}])
    groups_paginator = _mock_paginator([{"Groups": []}])
    keys_paginator = _mock_paginator([{"AccessKeyMetadata": []}])

    paginators = iter([policies_paginator, inline_paginator, groups_paginator, keys_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        user.delete()

    mock_client.detach_user_policy.assert_not_called()
    mock_client.delete_user_policy.assert_not_called()
    mock_client.delete_access_key.assert_not_called()
    mock_client.delete_user.assert_called_once_with(UserName="alice")


def test_delete_not_exists():
    """delete() on a non-existent user is a no-op."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator([{"AttachedPolicies": []}])
    inline_paginator = _mock_paginator([{"PolicyNames": []}])
    groups_paginator = _mock_paginator([{"Groups": []}])
    keys_paginator = _mock_paginator([{"AccessKeyMetadata": []}])

    paginators = iter([policies_paginator, inline_paginator, groups_paginator, keys_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)
    mock_client.delete_user.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        user.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    user = IAMUser("alice", region="us-east-1")
    mock_client = mock.MagicMock()

    policies_paginator = _mock_paginator([{"AttachedPolicies": []}])
    inline_paginator = _mock_paginator([{"PolicyNames": []}])
    groups_paginator = _mock_paginator([{"Groups": []}])
    keys_paginator = _mock_paginator([{"AccessKeyMetadata": []}])

    paginators = iter([policies_paginator, inline_paginator, groups_paginator, keys_paginator])
    mock_client.get_paginator.side_effect = lambda _operation: next(paginators)
    mock_client.delete_user.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            user.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
