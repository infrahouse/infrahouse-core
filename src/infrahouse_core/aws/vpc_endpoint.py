"""
VPC Endpoint resource wrapper.

Provides ``exists`` / ``delete()`` support for EC2 VPC endpoints.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class VPCEndpoint(AWSResource):
    """Wrapper around an EC2 VPC Endpoint.

    :param vpc_endpoint_id: VPC endpoint ID (e.g. ``vpce-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, vpc_endpoint_id, region=None, role_arn=None, session=None):
        super().__init__(vpc_endpoint_id, "ec2", region=region, role_arn=role_arn, session=session)

    @property
    def vpc_endpoint_id(self) -> str:
        """Return the VPC endpoint ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the VPC endpoint exists and is not deleted."""
        try:
            response = self._client.describe_vpc_endpoints(VpcEndpointIds=[self._resource_id])
            endpoints = response.get("VpcEndpoints", [])
            if not endpoints:
                return False
            return endpoints[0].get("State") != "deleted"
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidVpcEndpointId.NotFound":
                return False
            raise

    def delete(self) -> None:
        """Delete the VPC endpoint.

        Idempotent -- does nothing if the endpoint does not exist.
        """
        try:
            self._client.delete_vpc_endpoints(VpcEndpointIds=[self._resource_id])
            LOG.info("Deleted VPC endpoint %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidVpcEndpointId.NotFound":
                LOG.info("VPC endpoint %s does not exist.", self._resource_id)
            else:
                raise
