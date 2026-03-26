"""
Route Table resource wrapper.

Provides ``exists`` / ``delete()`` support for EC2 route tables.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class RouteTable(AWSResource):
    """Wrapper around an EC2 Route Table.

    :param route_table_id: Route table ID (e.g. ``rtb-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, route_table_id, region=None, role_arn=None, session=None):
        super().__init__(route_table_id, "ec2", region=region, role_arn=role_arn, session=session)

    @property
    def route_table_id(self) -> str:
        """Return the route table ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the route table exists."""
        try:
            self._client.describe_route_tables(RouteTableIds=[self._resource_id])
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidRouteTableID.NotFound":
                return False
            raise

    def delete(self) -> None:
        """Delete the route table.

        Idempotent -- does nothing if the route table does not exist.
        """
        try:
            self._client.delete_route_table(RouteTableId=self._resource_id)
            LOG.info("Deleted route table %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidRouteTableID.NotFound":
                LOG.info("Route table %s does not exist.", self._resource_id)
            else:
                raise
