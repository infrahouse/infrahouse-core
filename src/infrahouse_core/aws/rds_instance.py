"""
RDS Instance resource wrapper.

Provides ``exists`` / ``delete()`` support for RDS DB instances.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class RDSInstance(AWSResource):
    """Wrapper around an RDS DB instance.

    :param db_instance_id: DB instance identifier.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, db_instance_id, region=None, role_arn=None, session=None):
        super().__init__(db_instance_id, "rds", region=region, role_arn=role_arn, session=session)

    @property
    def db_instance_id(self) -> str:
        """Return the DB instance identifier.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the DB instance exists."""
        try:
            self._client.describe_db_instances(DBInstanceIdentifier=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "DBInstanceNotFound":
                return False
            raise

    def delete(self) -> None:
        """Delete the DB instance, skipping the final snapshot.

        Idempotent -- does nothing if the instance does not exist.
        """
        try:
            self._client.delete_db_instance(
                DBInstanceIdentifier=self._resource_id,
                SkipFinalSnapshot=True,
            )
            LOG.info("Deleted RDS instance %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "DBInstanceNotFound":
                LOG.info("RDS instance %s does not exist.", self._resource_id)
            else:
                raise
