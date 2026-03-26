"""
Internet Gateway resource wrapper.

Provides ``exists`` / ``delete()`` support.  The gateway must be detached
from all VPCs before it can be deleted -- ``delete()`` handles this
automatically.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class InternetGateway(AWSResource):
    """Wrapper around an EC2 Internet Gateway.

    :param igw_id: Internet gateway ID (e.g. ``igw-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, igw_id, region=None, role_arn=None, session=None):
        super().__init__(igw_id, "ec2", region=region, role_arn=role_arn, session=session)

    @property
    def igw_id(self) -> str:
        """Return the internet gateway ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the internet gateway exists."""
        try:
            self._client.describe_internet_gateways(InternetGatewayIds=[self._resource_id])
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidInternetGatewayID.NotFound":
                return False
            raise

    def delete(self) -> None:
        """Detach from all VPCs and delete the internet gateway.

        Idempotent -- does nothing if the gateway does not exist.
        """
        # Detach from all VPCs first
        try:
            response = self._client.describe_internet_gateways(InternetGatewayIds=[self._resource_id])
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidInternetGatewayID.NotFound":
                LOG.info("Internet gateway %s does not exist.", self._resource_id)
                return
            raise

        for attachment in response["InternetGateways"][0].get("Attachments", []):
            vpc_id = attachment["VpcId"]
            self._client.detach_internet_gateway(InternetGatewayId=self._resource_id, VpcId=vpc_id)
            LOG.info("Detached internet gateway %s from VPC %s", self._resource_id, vpc_id)

        try:
            self._client.delete_internet_gateway(InternetGatewayId=self._resource_id)
            LOG.info("Deleted internet gateway %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidInternetGatewayID.NotFound":
                LOG.info("Internet gateway %s does not exist.", self._resource_id)
            else:
                raise
