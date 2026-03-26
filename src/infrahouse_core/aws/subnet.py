"""
Subnet resource wrapper.

Provides ``exists`` / ``delete()`` support for EC2 subnets.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class Subnet(AWSResource):
    """Wrapper around an EC2 Subnet.

    :param subnet_id: Subnet ID (e.g. ``subnet-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, subnet_id, region=None, role_arn=None, session=None):
        super().__init__(subnet_id, "ec2", region=region, role_arn=role_arn, session=session)

    @property
    def subnet_id(self) -> str:
        """Return the subnet ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the subnet exists."""
        try:
            self._client.describe_subnets(SubnetIds=[self._resource_id])
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidSubnetID.NotFound":
                return False
            raise

    def delete(self) -> None:
        """Delete the subnet.

        Idempotent -- does nothing if the subnet does not exist.
        """
        try:
            self._client.delete_subnet(SubnetId=self._resource_id)
            LOG.info("Deleted subnet %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidSubnetID.NotFound":
                LOG.info("Subnet %s does not exist.", self._resource_id)
            else:
                raise
