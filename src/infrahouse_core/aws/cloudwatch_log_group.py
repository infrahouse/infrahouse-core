"""
CloudWatch Log Group resource wrapper.

Provides ``exists`` / ``delete()`` support for CloudWatch Logs log groups.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws import get_client
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

    @property
    def retention_in_days(self) -> int | None:
        """Return the retention period in days, or ``None`` if set to never expire."""
        paginator = self._client.get_paginator("describe_log_groups")
        for page in paginator.paginate(logGroupNamePrefix=self._resource_id):
            for group in page.get("logGroups", []):
                if group["logGroupName"] == self._resource_id:
                    return group.get("retentionInDays")
        raise ValueError(f"Log group {self._resource_id} not found")

    def set_retention(self, days: int) -> None:
        """Set the retention policy on the log group.

        :param days: Retention period in days.  Must be a value accepted by
            the CloudWatch Logs API (1, 3, 5, 7, 14, 30, 60, 90, 120, 150,
            180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653).
        """
        self._client.put_retention_policy(
            logGroupName=self._resource_id,
            retentionInDays=days,
        )
        LOG.info("Set retention on %s to %d days", self._resource_id, days)

    @classmethod
    def list_log_groups(
        cls,
        prefix: str | None = None,
        region: str | None = None,
        role_arn: str | None = None,
        session=None,
    ) -> list[CloudWatchLogGroup]:
        """List log groups, optionally filtered by name prefix.

        :param prefix: Log group name prefix to filter on.
        :param region: AWS region.
        :param role_arn: IAM role ARN for cross-account access.
        :param session: Pre-configured ``boto3.Session``.
        :type session: boto3.Session or None
        :returns: List of :class:`CloudWatchLogGroup` instances.
        """
        if session is not None:
            client = session.client("logs", region_name=region)
        else:
            client = get_client("logs", region=region, role_arn=role_arn)

        paginator = client.get_paginator("describe_log_groups")
        kwargs = {}
        if prefix:
            kwargs["logGroupNamePrefix"] = prefix

        result = []
        for page in paginator.paginate(**kwargs):
            for group in page.get("logGroups", []):
                result.append(cls(group["logGroupName"], region=region, role_arn=role_arn, session=session))
        return result

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
