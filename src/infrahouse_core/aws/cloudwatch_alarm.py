"""
CloudWatch Alarm resource wrapper.

Provides ``exists`` / ``delete()`` support for CloudWatch alarms.
"""

from __future__ import annotations

from logging import getLogger

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class CloudWatchAlarm(AWSResource):
    """Wrapper around a CloudWatch alarm.

    :param alarm_name: Name of the alarm.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, alarm_name, region=None, role_arn=None, session=None):
        super().__init__(alarm_name, "cloudwatch", region=region, role_arn=role_arn, session=session)

    @property
    def alarm_name(self) -> str:
        """Return the name of the alarm.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the alarm exists.

        Checks both metric alarms and composite alarms returned by
        ``describe_alarms``.
        """
        response = self._client.describe_alarms(AlarmNames=[self._resource_id])
        if response.get("MetricAlarms"):
            return True
        if response.get("CompositeAlarms"):
            return True
        return False

    def delete(self) -> None:
        """Delete the alarm.

        Idempotent -- ``delete_alarms`` does not raise if the alarm does
        not exist.
        """
        self._client.delete_alarms(AlarmNames=[self._resource_id])
        LOG.info("Deleted CloudWatch alarm %s", self._resource_id)
