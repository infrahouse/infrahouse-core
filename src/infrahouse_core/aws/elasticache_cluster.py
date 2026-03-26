"""
ElastiCache Cluster resource wrapper.

Provides ``exists`` / ``delete()`` support for ElastiCache clusters.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ElastiCacheCluster(AWSResource):
    """Wrapper around an ElastiCache cluster.

    :param cluster_id: Cache cluster identifier.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, cluster_id, region=None, role_arn=None, session=None):
        super().__init__(cluster_id, "elasticache", region=region, role_arn=role_arn, session=session)

    @property
    def cluster_id(self) -> str:
        """Return the cluster identifier.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the cluster exists."""
        try:
            self._client.describe_cache_clusters(CacheClusterId=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "CacheClusterNotFound":
                return False
            raise

    def delete(self) -> None:
        """Delete the cluster.

        Idempotent -- does nothing if the cluster does not exist.
        """
        try:
            self._client.delete_cache_cluster(CacheClusterId=self._resource_id)
            LOG.info("Deleted ElastiCache cluster %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "CacheClusterNotFound":
                LOG.info("ElastiCache cluster %s does not exist.", self._resource_id)
            else:
                raise
