"""
SQS Queue resource wrapper.

Provides ``exists`` / ``delete()`` support for Amazon SQS queues.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)

# SQS uses different error codes depending on the API version / endpoint.
_QUEUE_NOT_FOUND_CODES = frozenset({"QueueDoesNotExist", "NonExistentQueue", "AWS.SimpleQueueService.NonExistentQueue"})


class SQSQueue(AWSResource):
    """Wrapper around an SQS queue.

    :param queue_url: URL of the SQS queue.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, queue_url, region=None, role_arn=None, session=None):
        super().__init__(queue_url, "sqs", region=region, role_arn=role_arn, session=session)

    @property
    def queue_url(self) -> str:
        """Return the URL of the queue.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the queue exists.

        Returns ``False`` if the API raises ``QueueDoesNotExist`` or
        ``NonExistentQueue``.
        """
        try:
            self._client.get_queue_attributes(
                QueueUrl=self._resource_id,
                AttributeNames=["QueueArn"],
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] in _QUEUE_NOT_FOUND_CODES:
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the queue.

        Idempotent -- does nothing if the queue does not exist.
        """
        try:
            self._client.delete_queue(QueueUrl=self._resource_id)
            LOG.info("Deleted SQS queue %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] in _QUEUE_NOT_FOUND_CODES:
                LOG.info("SQS queue %s does not exist.", self._resource_id)
            else:
                raise
