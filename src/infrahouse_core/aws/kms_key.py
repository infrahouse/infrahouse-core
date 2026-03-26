"""
KMS Key resource wrapper.

Provides ``exists`` / ``delete()`` support for KMS keys.  Note that KMS keys
cannot be immediately deleted -- they are scheduled for deletion with a
waiting period of 7--30 days.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class KMSKey(AWSResource):
    """Wrapper around a KMS key.

    :param key_id: Key ID, key ARN, alias name, or alias ARN.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, key_id, region=None, role_arn=None, session=None):
        super().__init__(key_id, "kms", region=region, role_arn=role_arn, session=session)

    @property
    def key_id(self) -> str:
        """Return the key identifier.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the key exists and is not pending deletion.

        Returns ``False`` if the key is not found or its state is
        ``PendingDeletion``.
        """
        try:
            response = self._client.describe_key(KeyId=self._resource_id)
            return response["KeyMetadata"]["KeyState"] != "PendingDeletion"
        except ClientError as err:
            if err.response["Error"]["Code"] == "NotFoundException":
                return False
            raise

    def delete(self, pending_window_in_days: int = 7) -> None:
        """Schedule the key for deletion.

        :param pending_window_in_days: Days before permanent deletion (7--30).
            Default is 7.

        Idempotent -- does nothing if the key is already pending deletion,
        does not exist, or is AWS-managed.
        """
        try:
            self._client.schedule_key_deletion(
                KeyId=self._resource_id,
                PendingWindowInDays=pending_window_in_days,
            )
            LOG.info("Scheduled KMS key %s for deletion in %d days", self._resource_id, pending_window_in_days)
        except ClientError as err:
            code = err.response["Error"]["Code"]
            if code == "NotFoundException":
                LOG.info("KMS key %s does not exist.", self._resource_id)
            elif code == "KMSInvalidStateException":
                LOG.info("KMS key %s is already pending deletion or is AWS-managed.", self._resource_id)
            else:
                raise
