"""
CloudFront Response Headers Policy resource wrapper.

Provides ``exists`` / ``delete()`` support for CloudFront response headers
policies.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class CloudFrontResponseHeadersPolicy(AWSResource):
    """Wrapper around a CloudFront response headers policy.

    :param policy_id: The response headers policy ID.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, policy_id, region=None, role_arn=None):
        super().__init__(policy_id, "cloudfront", region=region, role_arn=role_arn)

    @property
    def policy_id(self) -> str:
        """Return the response headers policy ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the response headers policy exists.

        Returns ``False`` if the API raises ``NoSuchResponseHeadersPolicy``.
        """
        try:
            self._client.get_response_headers_policy(Id=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchResponseHeadersPolicy":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the response headers policy.

        Fetches the current ETag and issues the delete call.

        Idempotent -- does nothing if the policy does not exist.

        .. note::

            ``ResponseHeadersPolicyInUse`` is **not** caught and will
            propagate to the caller.  The policy must be detached from all
            distributions first.
        """
        try:
            response = self._client.get_response_headers_policy(Id=self._resource_id)
            etag = response["ETag"]
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchResponseHeadersPolicy":
                LOG.info("CloudFront response headers policy %s does not exist.", self._resource_id)
                return
            raise

        self._client.delete_response_headers_policy(Id=self._resource_id, IfMatch=etag)
        LOG.info("Deleted CloudFront response headers policy %s", self._resource_id)
