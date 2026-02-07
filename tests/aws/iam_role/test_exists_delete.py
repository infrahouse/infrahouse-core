"""Tests for IAMRole.exists, IAMRole.delete(), and related properties/methods."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.iam_instance_profile import IAMInstanceProfile
from infrahouse_core.aws.iam_policy import IAMPolicy
from infrahouse_core.aws.iam_role import IAMRole


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


def test_exists_true():
    """exists returns True when the role is found."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_role.return_value = {"Role": {"RoleName": "my-role"}}

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert role.exists is True
        mock_client.get_role.assert_called_once_with(RoleName="my-role")


def test_exists_false():
    """exists returns False when the role does not exist."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_role.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert role.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_role.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = role.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- instance_profiles -------------------------------------------------------


def test_instance_profiles():
    """instance_profiles returns IAMInstanceProfile instances."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"InstanceProfiles": [{"InstanceProfileName": "profile-1"}, {"InstanceProfileName": "profile-2"}]}]
    )

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = role.instance_profiles

    assert len(result) == 2
    assert all(isinstance(p, IAMInstanceProfile) for p in result)
    assert result[0]._resource_id == "profile-1"
    assert result[1]._resource_id == "profile-2"


def test_instance_profiles_empty():
    """instance_profiles returns an empty list when no profiles exist."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"InstanceProfiles": []}])

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert role.instance_profiles == []


# -- delete ------------------------------------------------------------------


def test_delete_full_teardown():
    """delete() detaches policies, removes from profiles, then deletes the role."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()

    # Set up paginators
    managed_policies_paginator = _mock_paginator(
        [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123456789012:policy/pol-1"}]}]
    )
    inline_policies_paginator = _mock_paginator([{"PolicyNames": ["inline-1"]}])
    instance_profiles_paginator = _mock_paginator([{"InstanceProfiles": [{"InstanceProfileName": "profile-1"}]}])

    def get_paginator(operation):
        return {
            "list_attached_role_policies": managed_policies_paginator,
            "list_role_policies": inline_policies_paginator,
            "list_instance_profiles_for_role": instance_profiles_paginator,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator

    # IAMInstanceProfile.remove_role() calls get_instance_profile then remove_role_from_instance_profile
    profile_mock_client = mock.MagicMock()
    profile_mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {
            "InstanceProfileName": "profile-1",
            "Roles": [{"RoleName": "my-role"}],
        }
    }

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with mock.patch.object(
            IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=profile_mock_client
        ):
            role.delete()

    mock_client.detach_role_policy.assert_called_once_with(
        RoleName="my-role", PolicyArn="arn:aws:iam::123456789012:policy/pol-1"
    )
    mock_client.delete_role_policy.assert_called_once_with(RoleName="my-role", PolicyName="inline-1")
    profile_mock_client.remove_role_from_instance_profile.assert_called_once_with(
        InstanceProfileName="profile-1", RoleName="my-role"
    )
    mock_client.delete_role.assert_called_once_with(RoleName="my-role")


def test_delete_no_dependencies():
    """delete() works when the role has no policies or instance profiles."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()

    empty_managed = _mock_paginator([{"AttachedPolicies": []}])
    empty_inline = _mock_paginator([{"PolicyNames": []}])
    empty_profiles = _mock_paginator([{"InstanceProfiles": []}])

    def get_paginator(operation):
        return {
            "list_attached_role_policies": empty_managed,
            "list_role_policies": empty_inline,
            "list_instance_profiles_for_role": empty_profiles,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        role.delete()

    mock_client.detach_role_policy.assert_not_called()
    mock_client.delete_role_policy.assert_not_called()
    mock_client.delete_role.assert_called_once_with(RoleName="my-role")


def test_delete_not_exists():
    """delete() on a non-existent role is a no-op."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()

    empty_managed = _mock_paginator([{"AttachedPolicies": []}])
    empty_inline = _mock_paginator([{"PolicyNames": []}])
    empty_profiles = _mock_paginator([{"InstanceProfiles": []}])

    def get_paginator(operation):
        return {
            "list_attached_role_policies": empty_managed,
            "list_role_policies": empty_inline,
            "list_instance_profiles_for_role": empty_profiles,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator
    mock_client.delete_role.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        role.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()

    empty_managed = _mock_paginator([{"AttachedPolicies": []}])
    empty_inline = _mock_paginator([{"PolicyNames": []}])
    empty_profiles = _mock_paginator([{"InstanceProfiles": []}])

    def get_paginator(operation):
        return {
            "list_attached_role_policies": empty_managed,
            "list_role_policies": empty_inline,
            "list_instance_profiles_for_role": empty_profiles,
        }[operation]

    mock_client.get_paginator.side_effect = get_paginator
    mock_client.delete_role.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            role.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- managed_policies --------------------------------------------------------


def test_managed_policies():
    """managed_policies returns a list of IAMPolicy objects."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()

    paginator = _mock_paginator(
        [
            {
                "AttachedPolicies": [
                    {"PolicyArn": "arn:aws:iam::123456789012:policy/pol-1"},
                    {"PolicyArn": "arn:aws:iam::123456789012:policy/pol-2"},
                ]
            }
        ]
    )
    mock_client.get_paginator.return_value = paginator

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = role.managed_policies

    assert len(result) == 2
    assert all(isinstance(p, IAMPolicy) for p in result)
    assert result[0].policy_arn == "arn:aws:iam::123456789012:policy/pol-1"
    assert result[1].policy_arn == "arn:aws:iam::123456789012:policy/pol-2"


def test_managed_policies_empty():
    """managed_policies returns an empty list when no policies are attached."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()

    paginator = _mock_paginator([{"AttachedPolicies": []}])
    mock_client.get_paginator.return_value = paginator

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = role.managed_policies

    assert result == []


def test_detach_policy():
    """detach_policy() calls detach_role_policy with the policy ARN."""
    role = IAMRole("my-role", region="us-east-1")
    mock_client = mock.MagicMock()
    policy = IAMPolicy("arn:aws:iam::123456789012:policy/pol-1")

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        role.detach_policy(policy)

    mock_client.detach_role_policy.assert_called_once_with(
        RoleName="my-role", PolicyArn="arn:aws:iam::123456789012:policy/pol-1"
    )
