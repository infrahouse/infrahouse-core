"""
Elastic IP resource wrapper.

Provides ``exists`` / ``delete()`` support for EC2 Elastic IP addresses.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ElasticIP(AWSResource):
    """Wrapper around an EC2 Elastic IP address.

    :param allocation_id: Allocation ID (e.g. ``eipalloc-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, allocation_id, region=None, role_arn=None, session=None):
        super().__init__(allocation_id, "ec2", region=region, role_arn=role_arn, session=session)

    @property
    def allocation_id(self) -> str:
        """Return the allocation ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the Elastic IP exists."""
        try:
            self._client.describe_addresses(AllocationIds=[self._resource_id])
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidAddressID.NotFound":
                return False
            raise

    def delete(self) -> None:
        """Release the Elastic IP.

        Idempotent -- does nothing if the address does not exist.
        """
        try:
            self._client.release_address(AllocationId=self._resource_id)
            LOG.info("Released Elastic IP %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidAddressID.NotFound":
                LOG.info("Elastic IP %s does not exist.", self._resource_id)
            else:
                raise
