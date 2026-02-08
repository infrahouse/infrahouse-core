"""
CloudFront Function resource wrapper.

Provides ``exists`` / ``delete()`` support for CloudFront Functions.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class CloudFrontFunction(AWSResource):
    """Wrapper around a CloudFront Function.

    :param function_name: Name of the CloudFront function.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, function_name, region=None, role_arn=None, session=None):
        super().__init__(function_name, "cloudfront", region=region, role_arn=role_arn, session=session)

    @property
    def function_name(self) -> str:
        """Return the function name.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the CloudFront function exists.

        Returns ``False`` if the API raises ``NoSuchFunctionExists``.
        """
        try:
            self._client.describe_function(Name=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchFunctionExists":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the CloudFront function.

        Fetches the current ETag and issues the delete call.

        Idempotent -- does nothing if the function does not exist.

        .. note::

            ``FunctionInUse`` is **not** caught and will propagate to the
            caller.  The function must be disassociated from all cache
            behaviors first.
        """
        try:
            response = self._client.describe_function(Name=self._resource_id)
            etag = response["ETag"]
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchFunctionExists":
                LOG.info("CloudFront function %s does not exist.", self._resource_id)
                return
            raise

        self._client.delete_function(Name=self._resource_id, IfMatch=etag)
        LOG.info("Deleted CloudFront function %s", self._resource_id)
