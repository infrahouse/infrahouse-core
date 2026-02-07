"""
NAT Gateway resource wrapper.

Provides ``exists`` / ``delete()`` support.  NAT Gateways have no
dependencies to clean up before deletion, but ``exists`` must account
for the ``deleting`` and ``deleted`` lifecycle states.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)

# NAT Gateway states that mean the resource is effectively gone.
_GONE_STATES = frozenset({"deleting", "deleted"})


class NATGateway(AWSResource):
    """Wrapper around an EC2 NAT Gateway.

    :param nat_gateway_id: ID of the NAT Gateway (e.g. ``nat-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, nat_gateway_id, region=None, role_arn=None):
        super().__init__(nat_gateway_id, "ec2", region=region, role_arn=role_arn)

    @property
    def nat_gateway_id(self) -> str:
        """Return the ID of the NAT Gateway.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the NAT Gateway exists and is not being deleted.

        A NAT Gateway in the ``deleting`` or ``deleted`` state is considered
        non-existent.  Returns ``False`` if the API returns no results or
        raises ``NatGatewayNotFound``.
        """
        try:
            response = self._client.describe_nat_gateways(
                NatGatewayIds=[self._resource_id],
            )
            gateways = response.get("NatGateways", [])
            if not gateways:
                return False
            state = gateways[0].get("State", "")
            return state not in _GONE_STATES
        except ClientError as err:
            if err.response["Error"]["Code"] == "NatGatewayNotFound":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the NAT Gateway.

        Idempotent -- does nothing if the NAT Gateway does not exist
        or is already being deleted.
        """
        try:
            self._client.delete_nat_gateway(NatGatewayId=self._resource_id)
            LOG.info("Deleted NAT Gateway %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "NatGatewayNotFound":
                LOG.info("NAT Gateway %s does not exist.", self._resource_id)
            else:
                raise
