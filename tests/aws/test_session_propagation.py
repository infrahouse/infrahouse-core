"""Tests that child resources created internally inherit the parent's session.

Issue #98: When a resource class creates child resource objects internally
(e.g. during ``delete()`` teardown), those children must receive
``session=self._session`` so they use the same pre-configured credentials.
"""

# pylint: disable=protected-access,too-few-public-methods,not-an-iterable

from unittest import mock

from infrahouse_core.aws.iam_group import IAMGroup
from infrahouse_core.aws.iam_instance_profile import IAMInstanceProfile
from infrahouse_core.aws.iam_policy import IAMPolicy
from infrahouse_core.aws.iam_role import IAMRole
from infrahouse_core.aws.iam_user import IAMUser


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


# ---------------------------------------------------------------------------
# IAMInstanceProfile -> IAMRole
# ---------------------------------------------------------------------------


class TestIAMInstanceProfileSessionPropagation:
    """IAMInstanceProfile.role propagates session to IAMRole."""

    def test_role_inherits_session(self):
        """The IAMRole created by the role property carries the parent session."""
        mock_session = mock.MagicMock()
        profile = IAMInstanceProfile("my-profile", region="us-west-2", role_arn="arn:role", session=mock_session)
        mock_client = mock.MagicMock()
        mock_client.get_instance_profile.return_value = {
            "InstanceProfile": {
                "InstanceProfileName": "my-profile",
                "Roles": [{"RoleName": "my-role"}],
            }
        }

        with mock.patch.object(IAMInstanceProfile, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
            role = profile.role

        assert isinstance(role, IAMRole)
        assert role._session is mock_session
        assert role._region == "us-west-2"
        assert role._role_arn == "arn:role"


# ---------------------------------------------------------------------------
# IAMRole -> IAMPolicy, IAMInstanceProfile
# ---------------------------------------------------------------------------


class TestIAMRoleSessionPropagation:
    """IAMRole child resources inherit session."""

    def test_managed_policies_inherit_session(self):
        """IAMPolicy children created by managed_policies carry the parent session."""
        mock_session = mock.MagicMock()
        role = IAMRole("my-role", region="eu-west-1", role_arn="arn:role", session=mock_session)
        mock_client = mock.MagicMock()
        mock_client.get_paginator.return_value = _mock_paginator(
            [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123:policy/pol-1"}]}]
        )

        with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
            policies = role.managed_policies

        assert len(policies) == 1
        assert policies[0]._session is mock_session
        assert policies[0]._region == "eu-west-1"
        assert policies[0]._role_arn == "arn:role"

    def test_instance_profiles_inherit_session(self):
        """IAMInstanceProfile children created by instance_profiles carry the parent session."""
        mock_session = mock.MagicMock()
        role = IAMRole("my-role", region="eu-west-1", role_arn="arn:role", session=mock_session)
        mock_client = mock.MagicMock()
        mock_client.get_paginator.return_value = _mock_paginator(
            [{"InstanceProfiles": [{"InstanceProfileName": "profile-1"}]}]
        )

        with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
            profiles = role.instance_profiles

        assert len(profiles) == 1
        assert profiles[0]._session is mock_session
        assert profiles[0]._region == "eu-west-1"
        assert profiles[0]._role_arn == "arn:role"


# ---------------------------------------------------------------------------
# IAMPolicy -> IAMRole, IAMUser, IAMGroup
# ---------------------------------------------------------------------------


class TestIAMPolicySessionPropagation:
    """IAMPolicy child resources inherit session."""

    def test_attached_entities_inherit_session(self):
        """All three entity types (roles, users, groups) inherit the session."""
        mock_session = mock.MagicMock()
        policy = IAMPolicy(
            "arn:aws:iam::123:policy/pol-1", region="ap-southeast-1", role_arn="arn:role", session=mock_session
        )
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

        # Roles
        assert len(roles) == 1
        assert roles[0]._session is mock_session
        assert roles[0]._region == "ap-southeast-1"
        assert roles[0]._role_arn == "arn:role"

        # Users
        assert len(users) == 1
        assert users[0]._session is mock_session
        assert users[0]._region == "ap-southeast-1"
        assert users[0]._role_arn == "arn:role"

        # Groups
        assert len(groups) == 1
        assert groups[0]._session is mock_session
        assert groups[0]._region == "ap-southeast-1"
        assert groups[0]._role_arn == "arn:role"

    def test_attached_entities_no_session(self):
        """When no session is provided, child entities have session=None."""
        policy = IAMPolicy("arn:aws:iam::123:policy/pol-1", region="us-east-1")
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

        assert roles[0]._session is None
        assert users[0]._session is None
        assert groups[0]._session is None


# ---------------------------------------------------------------------------
# IAMGroup -> IAMUser, IAMPolicy
# ---------------------------------------------------------------------------


class TestIAMGroupSessionPropagation:
    """IAMGroup child resources inherit session."""

    def test_users_inherit_session(self):
        """IAMUser children created by the users property carry the parent session."""
        mock_session = mock.MagicMock()
        group = IAMGroup("admins", region="us-west-2", role_arn="arn:role", session=mock_session)
        mock_client = mock.MagicMock()
        mock_client.get_paginator.return_value = _mock_paginator(
            [{"Users": [{"UserName": "alice"}, {"UserName": "bob"}]}]
        )

        with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
            users = group.users

        assert len(users) == 2
        for user in users:
            assert user._session is mock_session
            assert user._region == "us-west-2"
            assert user._role_arn == "arn:role"

    def test_managed_policies_inherit_session(self):
        """IAMPolicy children created by managed_policies carry the parent session."""
        mock_session = mock.MagicMock()
        group = IAMGroup("admins", region="us-west-2", role_arn="arn:role", session=mock_session)
        mock_client = mock.MagicMock()
        mock_client.get_paginator.return_value = _mock_paginator(
            [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123:policy/pol-1"}]}]
        )

        with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
            policies = group.managed_policies

        assert len(policies) == 1
        assert policies[0]._session is mock_session
        assert policies[0]._region == "us-west-2"
        assert policies[0]._role_arn == "arn:role"


# ---------------------------------------------------------------------------
# IAMUser -> IAMGroup, IAMPolicy
# ---------------------------------------------------------------------------


class TestIAMUserSessionPropagation:
    """IAMUser child resources inherit session."""

    def test_groups_inherit_session(self):
        """IAMGroup children created by the groups property carry the parent session."""
        mock_session = mock.MagicMock()
        user = IAMUser("alice", region="eu-central-1", role_arn="arn:role", session=mock_session)
        mock_client = mock.MagicMock()
        mock_client.get_paginator.return_value = _mock_paginator(
            [{"Groups": [{"GroupName": "admins"}, {"GroupName": "devs"}]}]
        )

        with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
            groups = user.groups

        assert len(groups) == 2
        for group in groups:
            assert group._session is mock_session
            assert group._region == "eu-central-1"
            assert group._role_arn == "arn:role"

    def test_managed_policies_inherit_session(self):
        """IAMPolicy children created by managed_policies carry the parent session."""
        mock_session = mock.MagicMock()
        user = IAMUser("alice", region="eu-central-1", role_arn="arn:role", session=mock_session)
        mock_client = mock.MagicMock()
        mock_client.get_paginator.return_value = _mock_paginator(
            [{"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::123:policy/pol-1"}]}]
        )

        with mock.patch.object(IAMUser, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
            policies = user.managed_policies

        assert len(policies) == 1
        assert policies[0]._session is mock_session
        assert policies[0]._region == "eu-central-1"
        assert policies[0]._role_arn == "arn:role"
