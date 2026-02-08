"""
CloudWatch Log Group resource wrapper.

Provides ``exists`` / ``delete()`` support for CloudWatch Logs log groups.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class CloudWatchLogGroup(AWSResource):
    """Wrapper around a CloudWatch Logs log group.

    :param log_group_name: Name of the log group.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, log_group_name, region=None, role_arn=None, session=None):
        super().__init__(log_group_name, "logs", region=region, role_arn=role_arn, session=session)

    @property
    def log_group_name(self) -> str:
        """Return the name of the log group.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the log group exists.

        Uses ``describe_log_groups`` with a name prefix filter and checks
        for an exact match, since the API does not raise an error for
        missing log groups.
        """
        paginator = self._client.get_paginator("describe_log_groups")
        for page in paginator.paginate(logGroupNamePrefix=self._resource_id):
            for group in page.get("logGroups", []):
                if group["logGroupName"] == self._resource_id:
                    return True
        return False

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the log group.

        Idempotent -- does nothing if the log group does not exist.
        """
        try:
            self._client.delete_log_group(logGroupName=self._resource_id)
            LOG.info("Deleted CloudWatch log group %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                LOG.info("CloudWatch log group %s does not exist.", self._resource_id)
            else:
                raise
