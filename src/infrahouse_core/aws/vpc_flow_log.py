"""
VPC Flow Log resource wrapper.

Provides ``exists`` / ``delete()`` support for EC2 VPC flow logs.
"""

from __future__ import annotations

from logging import getLogger

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class VPCFlowLog(AWSResource):
    """Wrapper around an EC2 VPC Flow Log.

    :param flow_log_id: Flow log ID (e.g. ``fl-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, flow_log_id, region=None, role_arn=None, session=None):
        super().__init__(flow_log_id, "ec2", region=region, role_arn=role_arn, session=session)

    @property
    def flow_log_id(self) -> str:
        """Return the flow log ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the flow log exists.

        The ``describe_flow_logs`` API does not raise an error for
        non-existent IDs -- it returns an empty list instead.
        """
        response = self._client.describe_flow_logs(FlowLogIds=[self._resource_id])
        return len(response.get("FlowLogs", [])) > 0

    def delete(self) -> None:
        """Delete the flow log.

        Idempotent -- ``delete_flow_logs`` succeeds even if the flow log
        does not exist.
        """
        response = self._client.delete_flow_logs(FlowLogIds=[self._resource_id])
        unsuccessful = response.get("Unsuccessful", [])
        if unsuccessful:
            LOG.warning("Failed to delete flow log %s: %s", self._resource_id, unsuccessful)
        else:
            LOG.info("Deleted VPC flow log %s", self._resource_id)
