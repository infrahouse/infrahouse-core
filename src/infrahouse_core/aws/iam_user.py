"""
IAM User resource wrapper.

Provides ``exists`` / ``delete()`` support with dependency-aware teardown
(detach policies, delete inline policies, remove from groups,
delete access keys, then delete the user).
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError
from cached_property import cached_property_with_ttl

from infrahouse_core.aws.base import AWSResource

if TYPE_CHECKING:
    from infrahouse_core.aws.iam_group import IAMGroup
    from infrahouse_core.aws.iam_policy import IAMPolicy

LOG = getLogger(__name__)


class IAMUser(AWSResource):
    """Wrapper around an IAM user.

    :param user_name: Name of the IAM user.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, user_name, region=None, role_arn=None):
        super().__init__(user_name, "iam", region=region, role_arn=role_arn)

    @property
    def user_name(self) -> str:
        """Return the name of the user.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the user exists."""
        try:
            self._client.get_user(UserName=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                return False
            raise

    # -- Groups --------------------------------------------------------------

    @cached_property_with_ttl(ttl=10)
    def groups(self) -> list[IAMGroup]:
        """Return groups that this user belongs to.

        :return: List of :class:`IAMGroup` instances.
        :rtype: list[IAMGroup]
        """
        # pylint: disable-next=import-outside-toplevel
        from infrahouse_core.aws.iam_group import IAMGroup

        result = []
        paginator = self._client.get_paginator("list_groups_for_user")
        for page in paginator.paginate(UserName=self._resource_id):
            for group in page["Groups"]:
                result.append(IAMGroup(group["GroupName"], region=self._region, role_arn=self._role_arn))
        return result

    # -- Policy operations ---------------------------------------------------

    @cached_property_with_ttl(ttl=10)
    def managed_policies(self) -> list[IAMPolicy]:
        """Return managed policies attached to this user.

        :return: List of :class:`IAMPolicy` instances.
        :rtype: list[IAMPolicy]
        """
        # pylint: disable-next=import-outside-toplevel
        from infrahouse_core.aws.iam_policy import IAMPolicy

        policies = []
        paginator = self._client.get_paginator("list_attached_user_policies")
        for page in paginator.paginate(UserName=self._resource_id):
            for policy in page["AttachedPolicies"]:
                policies.append(IAMPolicy(policy["PolicyArn"], region=self._region, role_arn=self._role_arn))
        return policies

    def detach_policy(self, policy: IAMPolicy) -> None:
        """Detach a managed policy from the user.

        :param policy: The managed policy to detach.
        :type policy: IAMPolicy
        """
        self._client.detach_user_policy(
            UserName=self._resource_id,
            PolicyArn=policy.policy_arn,
        )
        LOG.debug("Detached policy %s from user %s", policy.policy_arn, self._resource_id)

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the user after removing all dependencies.

        Teardown order:
        1. Detach all managed policies.
        2. Delete all inline policies.
        3. Remove from all groups.
        4. Delete all access keys.
        5. Delete the user itself.

        Idempotent -- does nothing if the user does not exist.
        """
        try:
            self._detach_managed_policies()
            self._delete_inline_policies()
            self._remove_from_groups()
            self._delete_access_keys()
            self._client.delete_user(UserName=self._resource_id)
            LOG.info("Deleted IAM user %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                LOG.info("IAM user %s does not exist.", self._resource_id)
            else:
                raise

    def _detach_managed_policies(self) -> None:
        """Detach all managed policies from the user.

        Iterates through all attached managed policies (via :attr:`managed_policies`)
        and calls :meth:`detach_policy` for each one.

        :raises ClientError: If the IAM API call to detach a policy fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        policies = list(self.managed_policies)
        if policies:
            LOG.info("Detaching %d managed policies from user %s", len(policies), self._resource_id)
        for policy in policies:
            self.detach_policy(policy)

    def _delete_inline_policies(self) -> None:
        """Delete all inline policies from the user.

        Lists all inline policy names via ``list_user_policies`` pagination,
        then deletes each one with ``delete_user_policy``.

        :raises ClientError: If the IAM API call to list or delete a policy fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        policy_names = []
        paginator = self._client.get_paginator("list_user_policies")
        for page in paginator.paginate(UserName=self._resource_id):
            policy_names.extend(page["PolicyNames"])
        if policy_names:
            LOG.info("Deleting %d inline policies from user %s", len(policy_names), self._resource_id)
        for policy_name in policy_names:
            self._client.delete_user_policy(
                UserName=self._resource_id,
                PolicyName=policy_name,
            )
            LOG.debug("Deleted inline policy %s from user %s", policy_name, self._resource_id)

    def _remove_from_groups(self) -> None:
        """Remove the user from all groups.

        Iterates through all groups (via :attr:`groups`) and calls
        :meth:`~IAMGroup.remove_user` on each one.

        :raises ClientError: If the IAM API call to remove the user fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        groups = list(self.groups)
        if groups:
            LOG.info("Removing user %s from %d groups", self._resource_id, len(groups))
        for group in groups:
            group.remove_user(self)

    def _delete_access_keys(self) -> None:
        """Delete all access keys for the user.

        Lists all access keys via ``list_access_keys`` pagination, then
        deletes each one with ``delete_access_key``.

        :raises ClientError: If the IAM API call to list or delete keys fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        keys = []
        paginator = self._client.get_paginator("list_access_keys")
        for page in paginator.paginate(UserName=self._resource_id):
            keys.extend(page["AccessKeyMetadata"])
        if keys:
            LOG.info("Deleting %d access keys from user %s", len(keys), self._resource_id)
        for key in keys:
            self._client.delete_access_key(
                UserName=self._resource_id,
                AccessKeyId=key["AccessKeyId"],
            )
            LOG.debug("Deleted access key %s from user %s", key["AccessKeyId"], self._resource_id)
