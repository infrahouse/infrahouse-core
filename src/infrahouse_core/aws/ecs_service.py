"""
ECS Service resource wrapper.

Provides ``exists`` / ``delete()`` support plus service status queries.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ECSService(AWSResource):
    """Wrapper around an ECS service.

    :param cluster_name: Name or ARN of the ECS cluster.
    :param service_name: Name of the ECS service.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    :param session: Pre-configured ``boto3.Session``.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, cluster_name, service_name, region=None, role_arn=None, session=None
    ):
        super().__init__(service_name, "ecs", region=region, role_arn=role_arn, session=session)
        self._cluster_name = cluster_name

    @property
    def cluster_name(self) -> str:
        """Return the cluster name.

        :rtype: str
        """
        return self._cluster_name

    @property
    def service_name(self) -> str:
        """Return the service name.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the service exists and is ``ACTIVE``."""
        response = self._client.describe_services(
            cluster=self._cluster_name,
            services=[self._resource_id],
        )
        services = response.get("services", [])
        if not services:
            return False
        return services[0].get("status") == "ACTIVE"

    @property
    def status(self) -> str:
        """Return the service status string (``ACTIVE``, ``DRAINING``, ``INACTIVE``).

        :rtype: str
        """
        return self._describe()["status"]

    @property
    def task_definition_arn(self) -> str:
        """Return the ARN of the active task definition.

        :rtype: str
        """
        return self._describe()["taskDefinition"]

    @property
    def desired_count(self) -> int:
        """Return the current desired count.

        :rtype: int
        """
        return self._describe()["desiredCount"]

    @property
    def running_count(self) -> int:
        """Return the current running count.

        :rtype: int
        """
        return self._describe()["runningCount"]

    @property
    def is_steady_state(self) -> bool:
        """Return ``True`` if the service has reached steady state.

        Steady state means ``runningCount == desiredCount`` and all
        deployments have ``rolloutState == "COMPLETED"``.

        :rtype: bool
        """
        desc = self._describe()
        if desc["runningCount"] != desc["desiredCount"]:
            return False
        for deployment in desc.get("deployments", []):
            if deployment.get("rolloutState") != "COMPLETED":
                return False
        return True

    def delete(self) -> None:
        """Delete the service.

        Sets ``desiredCount`` to 0 then force-deletes the service.
        Idempotent -- does nothing if the service does not exist.
        """
        try:
            self._client.update_service(
                cluster=self._cluster_name,
                service=self._resource_id,
                desiredCount=0,
            )
            self._client.delete_service(
                cluster=self._cluster_name,
                service=self._resource_id,
                force=True,
            )
            LOG.info("Deleted ECS service %s in cluster %s", self._resource_id, self._cluster_name)
        except ClientError as err:
            error_code = err.response["Error"]["Code"]
            if error_code in ("ServiceNotFoundException", "ServiceNotActiveException", "ClusterNotFoundException"):
                LOG.info(
                    "ECS service %s in cluster %s does not exist.",
                    self._resource_id,
                    self._cluster_name,
                )
            else:
                raise

    def _describe(self) -> dict:
        """Return the service description dict.

        :raises RuntimeError: If the service is not found.
        :rtype: dict
        """
        response = self._client.describe_services(
            cluster=self._cluster_name,
            services=[self._resource_id],
        )
        services = response.get("services", [])
        if not services:
            raise RuntimeError(f"ECS service {self._resource_id} not found in cluster {self._cluster_name}")
        return services[0]
