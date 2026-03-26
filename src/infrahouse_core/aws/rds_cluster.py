"""
RDS Cluster resource wrapper.

Provides ``exists`` / ``delete()`` support for RDS DB clusters.
Deletion removes all cluster member instances first, then the cluster itself.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class RDSCluster(AWSResource):
    """Wrapper around an RDS DB cluster.

    :param db_cluster_id: DB cluster identifier.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, db_cluster_id, region=None, role_arn=None, session=None):
        super().__init__(db_cluster_id, "rds", region=region, role_arn=role_arn, session=session)

    @property
    def db_cluster_id(self) -> str:
        """Return the DB cluster identifier.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the DB cluster exists."""
        try:
            self._client.describe_db_clusters(DBClusterIdentifier=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "DBClusterNotFoundFault":
                return False
            raise

    def delete(self) -> None:
        """Delete the cluster and all its member instances.

        Deletes all cluster member DB instances first (skipping final
        snapshots), then deletes the cluster itself.

        Idempotent -- does nothing if the cluster does not exist.
        """
        # Get cluster members before deletion
        try:
            response = self._client.describe_db_clusters(DBClusterIdentifier=self._resource_id)
            members = response["DBClusters"][0].get("DBClusterMembers", [])
        except ClientError as err:
            if err.response["Error"]["Code"] == "DBClusterNotFoundFault":
                LOG.info("RDS cluster %s does not exist.", self._resource_id)
                return
            raise

        # Delete member instances first
        for member in members:
            instance_id = member["DBInstanceIdentifier"]
            try:
                self._client.delete_db_instance(
                    DBInstanceIdentifier=instance_id,
                    SkipFinalSnapshot=True,
                )
                LOG.info("Deleted RDS cluster member instance %s", instance_id)
            except ClientError as err:
                if err.response["Error"]["Code"] == "DBInstanceNotFound":
                    LOG.info("RDS cluster member instance %s does not exist.", instance_id)
                else:
                    raise

        # Delete the cluster
        try:
            self._client.delete_db_cluster(
                DBClusterIdentifier=self._resource_id,
                SkipFinalSnapshot=True,
            )
            LOG.info("Deleted RDS cluster %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "DBClusterNotFoundFault":
                LOG.info("RDS cluster %s does not exist.", self._resource_id)
            else:
                raise
