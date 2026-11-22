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

    def __init__(self, profile_name, region=None, role_arn=None, session=None):
        super().__init__(profile_name, "iam", region=region, role_arn=role_arn, session=session)

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
            return IAMRole(roles[0]["RoleName"], region=self._region, role_arn=self._role_arn, session=self._session)
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

    # -- Tag helpers (IAM instance profile-specific) -------------------------
    #
    # IAM has no ``list_tags_for_resource``.  Instance profiles use
    # ``list_instance_profile_tags`` / ``tag_instance_profile`` /
    # ``untag_instance_profile``, keyed by instance profile name.

    @property
    def arn(self) -> str:
        """Return the ARN of the instance profile, from ``get_instance_profile``.

        :raises ClientError: ``NoSuchEntity`` if the instance profile does not exist.
        """
        return self._client.get_instance_profile(InstanceProfileName=self._resource_id)["InstanceProfile"]["Arn"]

    @property
    def tags(self) -> dict:
        """Return current tags as a ``{key: value}`` dict, read from every page of ``list_instance_profile_tags``.

        :raises ClientError: ``NoSuchEntity`` if the instance profile does not exist.
        """
        paginator = self._client.get_paginator("list_instance_profile_tags")
        pages = paginator.paginate(InstanceProfileName=self._resource_id)
        return {tag["Key"]: tag["Value"] for page in pages for tag in page["Tags"]}

    def set_tag(self, key: str, value: str) -> bool:
        """Set a single tag on the instance profile with ``tag_instance_profile``.

        Idempotent: if the tag is already set to ``value``, no API call is made.

        :param key: Tag key.
        :param value: Tag value.
        :returns: ``True`` if the tag was written, ``False`` if it was already current.
        :raises ClientError: ``NoSuchEntity`` if the instance profile does not exist.
        """
        if self.tags.get(key) == value:
            return False
        self._client.tag_instance_profile(InstanceProfileName=self._resource_id, Tags=[{"Key": key, "Value": value}])
        LOG.info("Set tag %s=%s on IAM instance profile %s", key, value, self._resource_id)
        return True

    def set_tags(self, tags: dict) -> int:
        """Set multiple tags on the instance profile with one ``tag_instance_profile`` call.

        Idempotent: only tags whose value differs are written.  If none differ, no API call is made.

        :param tags: Mapping of tag keys to values.
        :returns: Number of tags actually written.
        :raises ClientError: ``NoSuchEntity`` if the instance profile does not exist.
        """
        current = self.tags
        to_write = {k: v for k, v in tags.items() if current.get(k) != v}
        if not to_write:
            return 0
        self._client.tag_instance_profile(
            InstanceProfileName=self._resource_id,
            Tags=[{"Key": k, "Value": v} for k, v in to_write.items()],
        )
        LOG.info("Set %d tag(s) on IAM instance profile %s", len(to_write), self._resource_id)
        return len(to_write)

    def remove_tag(self, key: str) -> bool:
        """Remove a single tag from the instance profile with ``untag_instance_profile``.

        Idempotent: if the tag is not set, no API call is made.

        :param key: Tag key to remove.
        :returns: ``True`` if the tag was present and removed, ``False`` if it was already absent.
        :raises ClientError: ``NoSuchEntity`` if the instance profile does not exist.
        """
        if key not in self.tags:
            return False
        self._client.untag_instance_profile(InstanceProfileName=self._resource_id, TagKeys=[key])
        LOG.info("Removed tag %s from IAM instance profile %s", key, self._resource_id)
        return True
