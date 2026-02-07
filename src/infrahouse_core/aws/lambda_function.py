"""
Lambda Function resource wrapper.

Provides ``exists`` / ``delete()`` support for AWS Lambda functions.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class LambdaFunction(AWSResource):
    """Wrapper around an AWS Lambda function.

    :param function_name: Name or ARN of the Lambda function.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, function_name, region=None, role_arn=None):
        super().__init__(function_name, "lambda", region=region, role_arn=role_arn)

    @property
    def function_name(self) -> str:
        """Return the name (or ARN) of the Lambda function.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the Lambda function exists.

        Returns ``False`` if the API raises ``ResourceNotFoundException``.
        """
        try:
            self._client.get_function(FunctionName=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the Lambda function.

        Idempotent -- does nothing if the function does not exist.
        """
        try:
            self._client.delete_function(FunctionName=self._resource_id)
            LOG.info("Deleted Lambda function %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                LOG.info("Lambda function %s does not exist.", self._resource_id)
            else:
                raise
