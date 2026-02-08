"""
ELB Load Balancer resource wrapper.

Provides ``exists`` / ``delete()`` support for ELBv2 (Application,
Network, and Gateway) load balancers.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ELBLoadBalancer(AWSResource):
    """Wrapper around an ELBv2 Load Balancer.

    :param load_balancer_arn: ARN of the load balancer.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, load_balancer_arn, region=None, role_arn=None, session=None):
        super().__init__(load_balancer_arn, "elbv2", region=region, role_arn=role_arn, session=session)

    @property
    def load_balancer_arn(self) -> str:
        """Return the ARN of the load balancer.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the load balancer exists.

        Returns ``False`` if the API raises ``LoadBalancerNotFoundException``.
        """
        try:
            self._client.describe_load_balancers(
                LoadBalancerArns=[self._resource_id],
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "LoadBalancerNotFoundException":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the load balancer.

        Idempotent -- does nothing if the load balancer does not exist.
        """
        try:
            self._client.delete_load_balancer(LoadBalancerArn=self._resource_id)
            LOG.info("Deleted load balancer %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "LoadBalancerNotFoundException":
                LOG.info("Load balancer %s does not exist.", self._resource_id)
            else:
                raise
