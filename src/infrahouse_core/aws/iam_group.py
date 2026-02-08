"""
IAM Group resource wrapper.

Provides ``exists`` / ``delete()`` support with dependency-aware teardown
(detach policies, delete inline policies, remove all users, then delete the group).
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError
from cached_property import cached_property_with_ttl

from infrahouse_core.aws.base import AWSResource

if TYPE_CHECKING:
    from infrahouse_core.aws.iam_policy import IAMPolicy
    from infrahouse_core.aws.iam_user import IAMUser

LOG = getLogger(__name__)


class IAMGroup(AWSResource):
    """Wrapper around an IAM group.

    :param group_name: Name of the IAM group.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, group_name, region=None, role_arn=None, session=None):
        super().__init__(group_name, "iam", region=region, role_arn=role_arn, session=session)

    @property
    def group_name(self) -> str:
        """Return the name of the group.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the group exists."""
        try:
            self._client.get_group(GroupName=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                return False
            raise

    # -- Users ---------------------------------------------------------------

    @cached_property_with_ttl(ttl=10)
    def users(self) -> list[IAMUser]:
        """Return users that belong to this group.

        :return: List of :class:`IAMUser` instances.
        :rtype: list[IAMUser]
        """
        # pylint: disable-next=import-outside-toplevel
        from infrahouse_core.aws.iam_user import IAMUser

        result = []
        paginator = self._client.get_paginator("get_group")
        for page in paginator.paginate(GroupName=self._resource_id):
            for user in page["Users"]:
                result.append(IAMUser(user["UserName"], region=self._region, role_arn=self._role_arn))
        return result

    def remove_user(self, user: IAMUser) -> None:
        """Remove a user from this group.

        :param user: The IAM user to remove.
        :type user: IAMUser
        """
        self._client.remove_user_from_group(
            GroupName=self._resource_id,
            UserName=user.user_name,
        )
        LOG.debug("Removed user %s from group %s", user.user_name, self._resource_id)

    # -- Policy operations ---------------------------------------------------

    @cached_property_with_ttl(ttl=10)
    def managed_policies(self) -> list[IAMPolicy]:
        """Return managed policies attached to this group.

        :return: List of :class:`IAMPolicy` instances.
        :rtype: list[IAMPolicy]
        """
        # pylint: disable-next=import-outside-toplevel
        from infrahouse_core.aws.iam_policy import IAMPolicy

        policies = []
        paginator = self._client.get_paginator("list_attached_group_policies")
        for page in paginator.paginate(GroupName=self._resource_id):
            for policy in page["AttachedPolicies"]:
                policies.append(IAMPolicy(policy["PolicyArn"], region=self._region, role_arn=self._role_arn))
        return policies

    def detach_policy(self, policy: IAMPolicy) -> None:
        """Detach a managed policy from the group.

        :param policy: The managed policy to detach.
        :type policy: IAMPolicy
        """
        self._client.detach_group_policy(
            GroupName=self._resource_id,
            PolicyArn=policy.policy_arn,
        )
        LOG.debug("Detached policy %s from group %s", policy.policy_arn, self._resource_id)

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the group after removing all dependencies.

        Teardown order:
        1. Detach all managed policies.
        2. Delete all inline policies.
        3. Remove all users from the group.
        4. Delete the group itself.

        Idempotent -- does nothing if the group does not exist.
        """
        try:
            self._detach_managed_policies()
            self._delete_inline_policies()
            self._remove_all_users()
            self._client.delete_group(GroupName=self._resource_id)
            LOG.info("Deleted IAM group %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                LOG.info("IAM group %s does not exist.", self._resource_id)
            else:
                raise

    def _detach_managed_policies(self) -> None:
        """Detach all managed policies from the group.

        Iterates through all attached managed policies (via :attr:`managed_policies`)
        and calls :meth:`detach_policy` for each one.

        :raises ClientError: If the IAM API call to detach a policy fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        policies = list(self.managed_policies)
        if policies:
            LOG.info("Detaching %d managed policies from group %s", len(policies), self._resource_id)
        for policy in policies:
            self.detach_policy(policy)

    def _delete_inline_policies(self) -> None:
        """Delete all inline policies from the group.

        Lists all inline policy names via ``list_group_policies`` pagination,
        then deletes each one with ``delete_group_policy``.

        :raises ClientError: If the IAM API call to list or delete a policy fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        policy_names = []
        paginator = self._client.get_paginator("list_group_policies")
        for page in paginator.paginate(GroupName=self._resource_id):
            policy_names.extend(page["PolicyNames"])
        if policy_names:
            LOG.info("Deleting %d inline policies from group %s", len(policy_names), self._resource_id)
        for policy_name in policy_names:
            self._client.delete_group_policy(
                GroupName=self._resource_id,
                PolicyName=policy_name,
            )
            LOG.debug("Deleted inline policy %s from group %s", policy_name, self._resource_id)

    def _remove_all_users(self) -> None:
        """Remove all users from the group.

        Iterates through all users (via :attr:`users`) and calls
        :meth:`remove_user` for each one.

        :raises ClientError: If the IAM API call to remove a user fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        users = list(self.users)
        if users:
            LOG.info("Removing %d users from group %s", len(users), self._resource_id)
        for user in users:
            self.remove_user(user)
