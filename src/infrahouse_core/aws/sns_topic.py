"""
SNS Topic resource wrapper.

Provides ``exists`` / ``delete()`` support for Amazon SNS topics.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class SNSTopic(AWSResource):
    """Wrapper around an SNS topic.

    :param topic_arn: ARN of the SNS topic.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, topic_arn, region=None, role_arn=None):
        super().__init__(topic_arn, "sns", region=region, role_arn=role_arn)

    @property
    def topic_arn(self) -> str:
        """Return the ARN of the topic.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the topic exists.

        Returns ``False`` if the API raises ``NotFoundException``.
        """
        try:
            self._client.get_topic_attributes(TopicArn=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NotFoundException":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the topic.

        Idempotent -- SNS ``delete_topic`` does not raise an error if the
        topic does not exist.
        """
        self._client.delete_topic(TopicArn=self._resource_id)
        LOG.info("Deleted SNS topic %s", self._resource_id)
