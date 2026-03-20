"""
ECS Task Definition resource wrapper.

Provides ``exists`` / ``delete()`` support plus container image queries.
"""

from __future__ import annotations

from logging import getLogger
from typing import List

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ECSTaskDefinition(AWSResource):
    """Wrapper around an ECS task definition.

    :param task_definition_arn: Full ARN of the task definition
        (e.g. ``arn:aws:ecs:us-west-2:123456789012:task-definition/my-task:3``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    :param session: Pre-configured ``boto3.Session``.
    """

    def __init__(self, task_definition_arn, region=None, role_arn=None, session=None):
        super().__init__(task_definition_arn, "ecs", region=region, role_arn=role_arn, session=session)

    @property
    def task_definition_arn(self) -> str:
        """Return the task definition ARN.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the task definition exists and is ``ACTIVE``."""
        try:
            response = self._client.describe_task_definition(
                taskDefinition=self._resource_id,
            )
            return response["taskDefinition"].get("status") == "ACTIVE"
        except ClientError as err:
            if err.response["Error"]["Code"] == "ClientException":
                return False
            raise

    @property
    def container_images(self) -> List[str]:
        """Return image URIs from all container definitions.

        :rtype: list[str]
        """
        response = self._client.describe_task_definition(
            taskDefinition=self._resource_id,
        )
        return [c["image"] for c in response["taskDefinition"]["containerDefinitions"]]

    def delete(self) -> None:
        """Deregister the task definition (mark it ``INACTIVE``).

        Idempotent -- does nothing if the task definition does not exist.
        """
        try:
            self._client.deregister_task_definition(
                taskDefinition=self._resource_id,
            )
            LOG.info("Deregistered task definition %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ClientException":
                LOG.info("Task definition %s does not exist.", self._resource_id)
            else:
                raise
