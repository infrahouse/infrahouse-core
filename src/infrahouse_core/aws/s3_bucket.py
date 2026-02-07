"""
S3 Bucket resource wrapper.

Provides ``exists`` / ``delete()`` support with dependency-aware teardown
(delete all object versions and delete markers, then delete the bucket).
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)

# S3 delete_objects accepts at most 1000 keys per call.
_MAX_KEYS_PER_DELETE = 1000


class S3Bucket(AWSResource):
    """Wrapper around an S3 bucket.

    :param bucket_name: Name of the S3 bucket.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, bucket_name, region=None, role_arn=None):
        super().__init__(bucket_name, "s3", region=region, role_arn=role_arn)

    @property
    def bucket_name(self) -> str:
        """Return the name of the bucket.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the bucket exists."""
        try:
            self._client.head_bucket(Bucket=self._resource_id)
            return True
        except ClientError as err:
            error_code = int(err.response["Error"]["Code"])
            if error_code == 404:
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the bucket after removing all objects.

        Teardown order:
        1. Delete all object versions and delete markers.
        2. Delete the bucket itself.

        Idempotent -- does nothing if the bucket does not exist.
        """
        try:
            self._delete_all_objects()
            self._client.delete_bucket(Bucket=self._resource_id)
            LOG.info("Deleted S3 bucket %s", self._resource_id)
        except ClientError as err:
            error_code = err.response["Error"]["Code"]
            if error_code in ("NoSuchBucket", "404"):
                LOG.info("S3 bucket %s does not exist.", self._resource_id)
            else:
                raise

    def _delete_all_objects(self) -> None:
        """Delete all object versions and delete markers from the bucket.

        Paginates through ``list_object_versions`` and uses batch
        ``delete_objects`` calls (up to 1000 keys per call) to remove
        all versions and delete markers.

        :raises ClientError: If the S3 API call to list or delete objects fails.
            ``NoSuchBucket`` errors are not caught here; the caller is
            responsible for handling them.
        """
        paginator = self._client.get_paginator("list_object_versions")
        total_deleted = 0

        for page in paginator.paginate(Bucket=self._resource_id):
            objects = []
            for version in page.get("Versions", []):
                objects.append({"Key": version["Key"], "VersionId": version["VersionId"]})
            for marker in page.get("DeleteMarkers", []):
                objects.append({"Key": marker["Key"], "VersionId": marker["VersionId"]})

            if not objects:
                continue

            # Batch into chunks of _MAX_KEYS_PER_DELETE
            for i in range(0, len(objects), _MAX_KEYS_PER_DELETE):
                batch = objects[i : i + _MAX_KEYS_PER_DELETE]
                self._client.delete_objects(
                    Bucket=self._resource_id,
                    Delete={"Objects": batch, "Quiet": True},
                )
                total_deleted += len(batch)
                LOG.debug(
                    "Deleted batch of %d objects from bucket %s",
                    len(batch),
                    self._resource_id,
                )

        if total_deleted:
            LOG.info("Deleted %d object versions from bucket %s", total_deleted, self._resource_id)
