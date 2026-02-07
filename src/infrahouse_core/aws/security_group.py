"""
Security Group resource wrapper.

Provides ``exists`` / ``delete()`` support.  Security Groups have no
automatic dependency cleanup -- if other resources (ENIs, other SG rules)
still reference the group, ``delete()`` will raise ``DependencyViolation``.
The caller is responsible for removing dependencies first.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class SecurityGroup(AWSResource):
    """Wrapper around an EC2 Security Group.

    :param group_id: ID of the Security Group (e.g. ``sg-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, group_id, region=None, role_arn=None):
        super().__init__(group_id, "ec2", region=region, role_arn=role_arn)

    @property
    def group_id(self) -> str:
        """Return the ID of the Security Group.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the Security Group exists.

        Returns ``False`` if the API raises ``InvalidGroup.NotFound``.
        """
        try:
            self._client.describe_security_groups(
                GroupIds=[self._resource_id],
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidGroup.NotFound":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the Security Group.

        Idempotent -- does nothing if the Security Group does not exist.

        .. warning::

            If other resources (ENIs, other security group rules, etc.)
            still reference this group, AWS will raise
            ``DependencyViolation``.  The caller is responsible for
            removing dependencies before calling ``delete()``.
        """
        try:
            self._client.delete_security_group(GroupId=self._resource_id)
            LOG.info("Deleted Security Group %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidGroup.NotFound":
                LOG.info("Security Group %s does not exist.", self._resource_id)
            else:
                raise
