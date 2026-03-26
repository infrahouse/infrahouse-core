"""
OpenSearch Domain resource wrapper.

Provides ``exists`` / ``delete()`` support for OpenSearch domains.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class OpenSearchDomain(AWSResource):
    """Wrapper around an OpenSearch domain.

    :param domain_name: Domain name.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, domain_name, region=None, role_arn=None, session=None):
        super().__init__(domain_name, "opensearch", region=region, role_arn=role_arn, session=session)

    @property
    def domain_name(self) -> str:
        """Return the domain name.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the domain exists and is not being deleted."""
        try:
            response = self._client.describe_domain(DomainName=self._resource_id)
            return not response["DomainStatus"].get("Deleted", False)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    def delete(self) -> None:
        """Delete the domain.

        Idempotent -- does nothing if the domain does not exist.
        """
        try:
            self._client.delete_domain(DomainName=self._resource_id)
            LOG.info("Deleted OpenSearch domain %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                LOG.info("OpenSearch domain %s does not exist.", self._resource_id)
            else:
                raise
