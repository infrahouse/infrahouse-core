"""
ELB Target Group resource wrapper.

Provides ``exists`` / ``delete()`` support for ELBv2 target groups.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ELBTargetGroup(AWSResource):
    """Wrapper around an ELBv2 Target Group.

    :param target_group_arn: ARN of the target group.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, target_group_arn, region=None, role_arn=None):
        super().__init__(target_group_arn, "elbv2", region=region, role_arn=role_arn)

    @property
    def target_group_arn(self) -> str:
        """Return the ARN of the target group.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the target group exists.

        Returns ``False`` if the API raises ``TargetGroupNotFoundException``.
        """
        try:
            self._client.describe_target_groups(
                TargetGroupArns=[self._resource_id],
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "TargetGroupNotFoundException":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the target group.

        Idempotent -- does nothing if the target group does not exist.
        """
        try:
            self._client.delete_target_group(TargetGroupArn=self._resource_id)
            LOG.info("Deleted target group %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "TargetGroupNotFoundException":
                LOG.info("Target group %s does not exist.", self._resource_id)
            else:
                raise
