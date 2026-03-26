"""
VPC resource wrapper.

Provides ``exists`` / ``delete()`` support for EC2 VPCs.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource
from infrahouse_core.aws.vpc_endpoint import VPCEndpoint
from infrahouse_core.aws.vpc_flow_log import VPCFlowLog

LOG = getLogger(__name__)


class VPC(AWSResource):
    """Wrapper around an EC2 VPC.

    :param vpc_id: VPC ID (e.g. ``vpc-0123456789abcdef0``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, vpc_id, region=None, role_arn=None, session=None):
        super().__init__(vpc_id, "ec2", region=region, role_arn=role_arn, session=session)

    @property
    def vpc_id(self) -> str:
        """Return the VPC ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the VPC exists."""
        try:
            self._client.describe_vpcs(VpcIds=[self._resource_id])
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidVpcID.NotFound":
                return False
            raise

    @property
    def vpc_endpoints(self) -> list[VPCEndpoint]:
        """Return all VPC endpoints associated with this VPC.

        :rtype: list[VPCEndpoint]
        """
        endpoints = []
        paginator = self._client.get_paginator("describe_vpc_endpoints")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [self._resource_id]}]):
            for ep in page.get("VpcEndpoints", []):
                endpoints.append(
                    VPCEndpoint(
                        ep["VpcEndpointId"],
                        region=self._region,
                        role_arn=self._role_arn,
                        session=self._session,
                    )
                )
        return endpoints

    @property
    def flow_logs(self) -> list[VPCFlowLog]:
        """Return all flow logs associated with this VPC.

        :rtype: list[VPCFlowLog]
        """
        flow_logs = []
        paginator = self._client.get_paginator("describe_flow_logs")
        for page in paginator.paginate(Filters=[{"Name": "resource-id", "Values": [self._resource_id]}]):
            for fl in page.get("FlowLogs", []):
                flow_logs.append(
                    VPCFlowLog(
                        fl["FlowLogId"],
                        region=self._region,
                        role_arn=self._role_arn,
                        session=self._session,
                    )
                )
        return flow_logs

    def delete(self) -> None:
        """Delete the VPC.

        Idempotent -- does nothing if the VPC does not exist.

        .. warning::

            All dependent resources (subnets, route tables, internet gateways,
            VPC endpoints, etc.) must be deleted before the VPC can be removed.
        """
        try:
            self._client.delete_vpc(VpcId=self._resource_id)
            LOG.info("Deleted VPC %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidVpcID.NotFound":
                LOG.info("VPC %s does not exist.", self._resource_id)
            else:
                raise
