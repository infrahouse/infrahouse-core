"""
IAM Role resource wrapper.

Provides ``exists`` / ``delete()`` support with dependency-aware teardown
(detach policies, remove from instance profiles, then delete the role).
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError
from cached_property import cached_property_with_ttl

from infrahouse_core.aws.base import AWSResource
from infrahouse_core.aws.iam_policy import IAMPolicy

if TYPE_CHECKING:
    from infrahouse_core.aws.iam_instance_profile import IAMInstanceProfile

LOG = getLogger(__name__)


class IAMRole(AWSResource):
    """Wrapper around an IAM role.

    :param role_name: Name of the IAM role.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, role_name, region=None, role_arn=None):
        super().__init__(role_name, "iam", region=region, role_arn=role_arn)

    @property
    def role_name(self) -> str:
        """Return the name of the role.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the role exists."""
        try:
            self._client.get_role(RoleName=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                return False
            raise

    def delete(self) -> None:
        """Delete the role after detaching all policies and instance profiles.

        Teardown order:
        1. Detach all managed policies.
        2. Delete all inline policies.
        3. Remove role from all instance profiles.
        4. Delete the role itself.

        Idempotent -- does nothing if the role does not exist.
        """
        try:
            self._detach_managed_policies()
            self._delete_inline_policies()
            self._remove_from_instance_profiles()
            self._client.delete_role(RoleName=self._resource_id)
            LOG.info("Deleted IAM role %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                LOG.info("IAM role %s does not exist.", self._resource_id)
            else:
                raise

    @cached_property_with_ttl(ttl=10)
    def managed_policies(self) -> list[IAMPolicy]:
        """Return a list of managed policies attached to the role.

        :return: List of :class:`IAMPolicy` instances.
        :rtype: list[IAMPolicy]
        """
        policies = []
        paginator = self._client.get_paginator("list_attached_role_policies")
        for page in paginator.paginate(RoleName=self._resource_id):
            for policy in page["AttachedPolicies"]:
                policies.append(IAMPolicy(policy["PolicyArn"], region=self._region, role_arn=self._role_arn))
        return policies

    def detach_policy(self, policy: IAMPolicy) -> None:
        """Detach a managed policy from the role.

        :param policy: The managed policy to detach.
        :type policy: IAMPolicy
        """
        self._client.detach_role_policy(
            RoleName=self._resource_id,
            PolicyArn=policy.policy_arn,
        )
        LOG.debug("Detached policy %s from role %s", policy.policy_arn, self._resource_id)

    def _detach_managed_policies(self) -> None:
        """Detach all managed policies from the role.

        Iterates through all attached managed policies (via :attr:`managed_policies`)
        and calls :meth:`detach_policy` for each one.

        :raises ClientError: If the IAM API call to detach a policy fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        policies = list(self.managed_policies)
        if policies:
            LOG.info("Detaching %d managed policies from role %s", len(policies), self._resource_id)
        for policy in policies:
            self.detach_policy(policy)

    def _delete_inline_policies(self) -> None:
        """Delete all inline policies from the role.

        Lists all inline policy names via ``list_role_policies`` pagination,
        then deletes each one with ``delete_role_policy``.

        :raises ClientError: If the IAM API call to list or delete a policy fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        policy_names = []
        paginator = self._client.get_paginator("list_role_policies")
        for page in paginator.paginate(RoleName=self._resource_id):
            policy_names.extend(page["PolicyNames"])
        if policy_names:
            LOG.info("Deleting %d inline policies from role %s", len(policy_names), self._resource_id)
        for policy_name in policy_names:
            self._client.delete_role_policy(
                RoleName=self._resource_id,
                PolicyName=policy_name,
            )
            LOG.debug("Deleted inline policy %s from role %s", policy_name, self._resource_id)

    @cached_property_with_ttl(ttl=10)
    def instance_profiles(self) -> list[IAMInstanceProfile]:
        """Return instance profiles that have this role attached.

        :return: List of :class:`IAMInstanceProfile` instances.
        :rtype: list[IAMInstanceProfile]
        """
        # pylint: disable-next=import-outside-toplevel
        from infrahouse_core.aws.iam_instance_profile import IAMInstanceProfile

        profiles = []
        paginator = self._client.get_paginator("list_instance_profiles_for_role")
        for page in paginator.paginate(RoleName=self._resource_id):
            for profile in page["InstanceProfiles"]:
                profiles.append(
                    IAMInstanceProfile(profile["InstanceProfileName"], region=self._region, role_arn=self._role_arn)
                )
        return profiles

    def _remove_from_instance_profiles(self) -> None:
        """Remove the role from all instance profiles.

        Iterates through all instance profiles (via :attr:`instance_profiles`)
        and calls :meth:`~IAMInstanceProfile.remove_role` on each one.

        :raises ClientError: If the IAM API call to remove the role fails.
            ``NoSuchEntity`` errors are not caught here; the caller is
            responsible for handling them.
        """
        profiles = list(self.instance_profiles)
        if profiles:
            LOG.info("Removing role %s from %d instance profiles", self._resource_id, len(profiles))
        for profile in profiles:
            profile.remove_role()
