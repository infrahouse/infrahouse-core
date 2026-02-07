"""Tests for IAMPolicy.exists, IAMPolicy.delete(), and related properties."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.iam_group import IAMGroup
from infrahouse_core.aws.iam_policy import IAMPolicy
from infrahouse_core.aws.iam_role import IAMRole
from infrahouse_core.aws.iam_user import IAMUser

POLICY_ARN = "arn:aws:iam::123456789012:policy/my-policy"
AWS_MANAGED_POLICY_ARN = "arn:aws:iam::aws:policy/ReadOnlyAccess"


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


def test_policy_arn():
    """policy_arn returns the ARN passed to the constructor."""
    policy = IAMPolicy(POLICY_ARN)
    assert policy.policy_arn == POLICY_ARN


def test_is_aws_managed_true():
    """is_aws_managed returns True for AWS-managed policy ARNs."""
    policy = IAMPolicy(AWS_MANAGED_POLICY_ARN)
    assert policy.is_aws_managed is True


def test_is_aws_managed_false():
    """is_aws_managed returns False for customer-managed policy ARNs."""
    policy = IAMPolicy(POLICY_ARN)
    assert policy.is_aws_managed is False


def test_exists_true():
    """exists returns True when the policy is found."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_policy.return_value = {"Policy": {"Arn": POLICY_ARN}}

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert policy.exists is True
        mock_client.get_policy.assert_called_once_with(PolicyArn=POLICY_ARN)


def test_exists_false():
    """exists returns False when the policy does not exist."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_policy.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert policy.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_policy.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = policy.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- attached_roles / attached_users / attached_groups -----------------------


def test_attached_roles():
    """attached_roles returns IAMRole instances."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"PolicyRoles": [{"RoleName": "role-1"}, {"RoleName": "role-2"}], "PolicyUsers": [], "PolicyGroups": []}]
    )

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = policy.attached_roles

    assert len(result) == 2
    assert all(isinstance(r, IAMRole) for r in result)
    assert result[0].role_name == "role-1"
    assert result[1].role_name == "role-2"


def test_attached_roles_empty():
    """attached_roles returns an empty list when no roles are attached."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"PolicyRoles": [], "PolicyUsers": [], "PolicyGroups": []}]
    )

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert policy.attached_roles == []


def test_attached_users():
    """attached_users returns IAMUser instances."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"PolicyRoles": [], "PolicyUsers": [{"UserName": "user-1"}], "PolicyGroups": []}]
    )

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = policy.attached_users

    assert len(result) == 1
    assert isinstance(result[0], IAMUser)
    assert result[0].user_name == "user-1"


def test_attached_groups():
    """attached_groups returns IAMGroup instances."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"PolicyRoles": [], "PolicyUsers": [], "PolicyGroups": [{"GroupName": "group-1"}]}]
    )

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = policy.attached_groups

    assert len(result) == 1
    assert isinstance(result[0], IAMGroup)
    assert result[0].group_name == "group-1"


def test_fetch_entities_single_api_call():
    """Accessing all three attached_* properties makes only one list_entities_for_policy call."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [
            {
                "PolicyRoles": [{"RoleName": "role-1"}],
                "PolicyUsers": [{"UserName": "user-1"}],
                "PolicyGroups": [{"GroupName": "group-1"}],
            }
        ]
    )

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        roles = policy.attached_roles
        users = policy.attached_users
        groups = policy.attached_groups

    # Only one paginator created — single API call sequence
    mock_client.get_paginator.assert_called_once_with("list_entities_for_policy")
    assert len(roles) == 1
    assert len(users) == 1
    assert len(groups) == 1


# -- delete ------------------------------------------------------------------


def test_delete_skips_aws_managed():
    """delete() is a no-op for AWS-managed policies."""
    policy = IAMPolicy(AWS_MANAGED_POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        policy.delete()

    # No API calls should be made
    mock_client.get_paginator.assert_not_called()
    mock_client.delete_policy.assert_not_called()


def test_delete_full_teardown():
    """delete() detaches from all entities, removes versions, then deletes."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    # _fetch_attached_entities makes a single list_entities_for_policy call,
    # _delete_non_default_versions calls list_policy_versions.
    entities_paginator = _mock_paginator(
        [
            {
                "PolicyRoles": [{"RoleName": "role-1"}],
                "PolicyUsers": [{"UserName": "user-1"}],
                "PolicyGroups": [{"GroupName": "group-1"}],
            }
        ]
    )
    versions_paginator = _mock_paginator(
        [
            {
                "Versions": [
                    {"VersionId": "v1", "IsDefaultVersion": True},
                    {"VersionId": "v2", "IsDefaultVersion": False},
                ]
            }
        ]
    )

    def get_paginator(operation):
        return {
            "list_entities_for_policy": entities_paginator,
            "list_policy_versions": versions_paginator,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator

    # _detach_from_all_entities calls role.detach_policy(self), user.detach_policy(self),
    # group.detach_policy(self) — each entity uses its own _client.
    role_mock_client = mock.MagicMock()
    user_mock_client = mock.MagicMock()
    group_mock_client = mock.MagicMock()

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=role_mock_client):
            with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=user_mock_client):
                with mock.patch.object(
                    IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=group_mock_client
                ):
                    policy.delete()

    role_mock_client.detach_role_policy.assert_called_once_with(RoleName="role-1", PolicyArn=POLICY_ARN)
    user_mock_client.detach_user_policy.assert_called_once_with(UserName="user-1", PolicyArn=POLICY_ARN)
    group_mock_client.detach_group_policy.assert_called_once_with(GroupName="group-1", PolicyArn=POLICY_ARN)
    # Only the non-default version should be deleted
    mock_client.delete_policy_version.assert_called_once_with(PolicyArn=POLICY_ARN, VersionId="v2")
    mock_client.delete_policy.assert_called_once_with(PolicyArn=POLICY_ARN)


def test_delete_no_dependencies():
    """delete() works when the policy has no attached entities or extra versions."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    entities_paginator = _mock_paginator([{"PolicyRoles": [], "PolicyUsers": [], "PolicyGroups": []}])
    versions_paginator = _mock_paginator([{"Versions": [{"VersionId": "v1", "IsDefaultVersion": True}]}])

    def get_paginator(operation):
        return {
            "list_entities_for_policy": entities_paginator,
            "list_policy_versions": versions_paginator,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        policy.delete()

    mock_client.delete_policy_version.assert_not_called()
    mock_client.delete_policy.assert_called_once_with(PolicyArn=POLICY_ARN)


def test_delete_not_exists():
    """delete() on a non-existent policy is a no-op."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    entities_paginator = _mock_paginator([{"PolicyRoles": [], "PolicyUsers": [], "PolicyGroups": []}])
    versions_paginator = _mock_paginator([{"Versions": [{"VersionId": "v1", "IsDefaultVersion": True}]}])

    def get_paginator(operation):
        return {
            "list_entities_for_policy": entities_paginator,
            "list_policy_versions": versions_paginator,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator
    mock_client.delete_policy.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        policy.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    policy = IAMPolicy(POLICY_ARN, region="us-east-1")
    mock_client = mock.MagicMock()

    entities_paginator = _mock_paginator([{"PolicyRoles": [], "PolicyUsers": [], "PolicyGroups": []}])
    versions_paginator = _mock_paginator([{"Versions": [{"VersionId": "v1", "IsDefaultVersion": True}]}])

    def get_paginator(operation):
        return {
            "list_entities_for_policy": entities_paginator,
            "list_policy_versions": versions_paginator,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator
    mock_client.delete_policy.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            policy.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
