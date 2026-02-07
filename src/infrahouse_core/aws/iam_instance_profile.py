"""
IAM Instance Profile resource wrapper.

Provides ``exists`` / ``delete()`` support with dependency-aware teardown
(remove all roles, then delete the instance profile).
"""

from __future__ import annotations

from logging import getLogger
from typing import Optional

from botocore.exceptions import ClientError
from cached_property import cached_property_with_ttl

from infrahouse_core.aws.base import AWSResource
from infrahouse_core.aws.iam_role import IAMRole

LOG = getLogger(__name__)


class IAMInstanceProfile(AWSResource):
    """Wrapper around an IAM instance profile.

    :param profile_name: Name of the IAM instance profile.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, profile_name, region=None, role_arn=None):
        super().__init__(profile_name, "iam", region=region, role_arn=role_arn)

    @property
    def profile_name(self) -> str:
        """Return the name of the instance profile.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the instance profile exists."""
        try:
            self._client.get_instance_profile(InstanceProfileName=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                return False
            raise

    @cached_property_with_ttl(ttl=10)
    def role(self) -> Optional[IAMRole]:
        """Return the IAM role associated with this instance profile, or ``None``.

        An instance profile can have at most one role.

        :return: The attached :class:`IAMRole`, or ``None`` if no role is attached.
        :rtype: IAMRole | None
        """
        response = self._client.get_instance_profile(InstanceProfileName=self._resource_id)
        roles = response["InstanceProfile"]["Roles"]
        if roles:
            return IAMRole(roles[0]["RoleName"], region=self._region, role_arn=self._role_arn)
        return None

    def delete(self) -> None:
        """Delete the instance profile after removing all roles.

        Teardown order:
        1. Remove all roles from the instance profile.
        2. Delete the instance profile itself.

        Idempotent -- does nothing if the instance profile does not exist.
        """
        try:
            self.remove_role()
            self._client.delete_instance_profile(InstanceProfileName=self._resource_id)
            LOG.info("Deleted IAM instance profile %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                LOG.info("IAM instance profile %s does not exist.", self._resource_id)
            else:
                raise

    def remove_role(self) -> None:
        """Remove the role from the instance profile, if one is attached."""
        role = self.role
        if role is None:
            return
        LOG.info("Removing role %s from instance profile %s", role.role_name, self._resource_id)
        try:
            self._client.remove_role_from_instance_profile(
                InstanceProfileName=self._resource_id,
                RoleName=role.role_name,
            )
            LOG.debug(
                "Removed role %s from instance profile %s",
                role.role_name,
                self._resource_id,
            )
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchEntity":
                LOG.debug("Role already removed from instance profile %s", self._resource_id)
            else:
                raise
