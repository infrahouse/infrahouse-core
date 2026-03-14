"""
ECR Repository resource wrapper.

Provides ``exists`` / ``delete()`` support plus image queries via :class:`ECRImage`.
"""

from __future__ import annotations

from logging import getLogger
from typing import List

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ECRImage:
    """Represents a single image in an ECR repository.

    Use :meth:`ECRRepository.get_image` to obtain instances.
    Exactly one of ``tag`` or ``digest`` must be provided.

    :param ecr_client: A boto3 ECR client.
    :param repository_name: Name of the ECR repository.
    :param tag: An image tag (e.g. ``"latest"``).
    :param digest: An image digest (e.g. ``"sha256:abc..."``).
    :raises ValueError: If neither or both of ``tag`` and ``digest`` are provided.
    """

    def __init__(self, ecr_client, repository_name: str, tag: str = None, digest: str = None):
        if tag and digest:
            raise ValueError("Specify either tag or digest, not both.")
        if not tag and not digest:
            raise ValueError("Either tag or digest must be provided.")
        self._client = ecr_client
        self._repository_name = repository_name
        self._tag = tag
        self._digest = digest

    @property
    def exists(self) -> bool:
        """Return ``True`` if the image exists in the repository."""
        try:
            response = self._client.describe_images(
                repositoryName=self._repository_name,
                imageIds=[self._image_id],
            )
            return bool(response.get("imageDetails"))
        except ClientError as err:
            if err.response["Error"]["Code"] == "ImageNotFoundException":
                return False
            raise

    @property
    def tags(self) -> List[str]:
        """Return all tags for this image.

        :rtype: list[str]
        :return: List of image tags. Empty list if the image is not found.
        """
        try:
            response = self._client.describe_images(
                repositoryName=self._repository_name,
                imageIds=[self._image_id],
            )
            if response.get("imageDetails"):
                return response["imageDetails"][0].get("imageTags", [])
            return []
        except ClientError as err:
            if err.response["Error"]["Code"] == "ImageNotFoundException":
                return []
            raise

    @property
    def digest(self) -> str | None:
        """Return the image digest.

        :rtype: str | None
        """
        try:
            response = self._client.describe_images(
                repositoryName=self._repository_name,
                imageIds=[self._image_id],
            )
            if response.get("imageDetails"):
                return response["imageDetails"][0].get("imageDigest")
            return None
        except ClientError as err:
            if err.response["Error"]["Code"] == "ImageNotFoundException":
                return None
            raise

    @property
    def _image_id(self) -> dict:
        """Return the ``imageIds`` element for this image.

        :rtype: dict
        """
        if self._digest:
            return {"imageDigest": self._digest}
        return {"imageTag": self._tag}


class ECRRepository(AWSResource):
    """Wrapper around an ECR repository.

    :param repository_name: Name of the ECR repository.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    :param session: Pre-configured ``boto3.Session``.
    """

    def __init__(self, repository_name, region=None, role_arn=None, session=None):
        super().__init__(repository_name, "ecr", region=region, role_arn=role_arn, session=session)

    @property
    def repository_name(self) -> str:
        """Return the name of the repository.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the repository exists."""
        try:
            self._client.describe_repositories(repositoryNames=[self._resource_id])
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "RepositoryNotFoundException":
                return False
            raise

    @property
    def repository_uri(self) -> str:
        """Return the full URI of the repository.

        :rtype: str
        :raises ClientError: If the repository does not exist.
        """
        response = self._client.describe_repositories(repositoryNames=[self._resource_id])
        return response["repositories"][0]["repositoryUri"]

    def get_image(self, tag: str = None, digest: str = None) -> ECRImage:
        """Return an :class:`ECRImage` for the given tag or digest.

        Exactly one of ``tag`` or ``digest`` must be provided.

        :param tag: An image tag (e.g. ``"latest"``).
        :param digest: An image digest (e.g. ``"sha256:abc..."``).
        :rtype: ECRImage
        """
        return ECRImage(self._client, self._resource_id, tag=tag, digest=digest)

    @property
    def images(self) -> List[ECRImage]:
        """Return all images in the repository.

        Paginates through ``describe_images`` to return all results.

        :rtype: list[ECRImage]
        """
        result = []
        paginator = self._client.get_paginator("describe_images")
        for page in paginator.paginate(repositoryName=self._resource_id):
            for detail in page.get("imageDetails", []):
                digest = detail.get("imageDigest")
                if digest:
                    result.append(ECRImage(self._client, self._resource_id, digest=digest))
        return result

    def delete(self) -> None:
        """Delete the repository and all its images.

        Idempotent -- does nothing if the repository does not exist.
        """
        try:
            self._client.delete_repository(repositoryName=self._resource_id, force=True)
            LOG.info("Deleted ECR repository %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "RepositoryNotFoundException":
                LOG.info("ECR repository %s does not exist.", self._resource_id)
            else:
                raise
