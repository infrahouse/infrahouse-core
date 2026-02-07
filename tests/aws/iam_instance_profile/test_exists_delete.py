"""Tests for IAMInstanceProfile.exists and IAMInstanceProfile.delete()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.iam_instance_profile import IAMInstanceProfile
from infrahouse_core.aws.iam_role import IAMRole


def _make_client_error(code):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def test_exists_true():
    """exists returns True when the instance profile is found."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {"InstanceProfileName": "my-profile", "Roles": []}
    }

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert profile.exists is True
        mock_client.get_instance_profile.assert_called_once_with(InstanceProfileName="my-profile")


def test_exists_false():
    """exists returns False when the instance profile does not exist."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert profile.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = profile.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


def test_delete_with_role():
    """delete() removes the role then deletes the instance profile."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {
            "InstanceProfileName": "my-profile",
            "Roles": [{"RoleName": "role-1"}],
        }
    }

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        profile.delete()

    mock_client.remove_role_from_instance_profile.assert_called_once_with(
        InstanceProfileName="my-profile", RoleName="role-1"
    )
    mock_client.delete_instance_profile.assert_called_once_with(InstanceProfileName="my-profile")


def test_delete_no_roles():
    """delete() works when the instance profile has no roles."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {"InstanceProfileName": "my-profile", "Roles": []}
    }

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        profile.delete()

    mock_client.remove_role_from_instance_profile.assert_not_called()
    mock_client.delete_instance_profile.assert_called_once_with(InstanceProfileName="my-profile")


def test_delete_not_exists():
    """delete() on a non-existent instance profile is a no-op."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    # get_instance_profile in remove_role() raises NoSuchEntity
    mock_client.get_instance_profile.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        profile.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {"InstanceProfileName": "my-profile", "Roles": []}
    }
    mock_client.delete_instance_profile.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            profile.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


def test_role_returns_iam_role():
    """role returns an IAMRole when the instance profile has a role."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {
            "InstanceProfileName": "my-profile",
            "Roles": [{"RoleName": "my-role"}],
        }
    }

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        result = profile.role

    assert isinstance(result, IAMRole)
    assert result.role_name == "my-role"


def test_role_returns_none():
    """role returns None when the instance profile has no role."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {"InstanceProfileName": "my-profile", "Roles": []}
    }

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert profile.role is None


def test_remove_role_with_role():
    """remove_role() removes the attached role."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {
            "InstanceProfileName": "my-profile",
            "Roles": [{"RoleName": "my-role"}],
        }
    }

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        profile.remove_role()

    mock_client.remove_role_from_instance_profile.assert_called_once_with(
        InstanceProfileName="my-profile", RoleName="my-role"
    )


def test_remove_role_no_role():
    """remove_role() is a no-op when no role is attached."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {"InstanceProfileName": "my-profile", "Roles": []}
    }

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        profile.remove_role()

    mock_client.remove_role_from_instance_profile.assert_not_called()


def test_remove_role_race_condition():
    """remove_role() handles the case where the role is removed between check and act."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    # role property sees a role attached
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {
            "InstanceProfileName": "my-profile",
            "Roles": [{"RoleName": "my-role"}],
        }
    }
    # but by the time we call remove, it's already gone
    mock_client.remove_role_from_instance_profile.side_effect = _make_client_error("NoSuchEntity")

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        profile.remove_role()  # Should not raise


def test_remove_role_unexpected_error():
    """remove_role() re-raises unexpected errors."""
    profile = IAMInstanceProfile("my-profile", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_instance_profile.return_value = {
        "InstanceProfile": {
            "InstanceProfileName": "my-profile",
            "Roles": [{"RoleName": "my-role"}],
        }
    }
    mock_client.remove_role_from_instance_profile.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            profile.remove_role()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"
