"""
Base class for AWS resource wrappers.

Provides a standard interface (``exists`` property and ``delete()`` method)
that all AWS resource classes should implement.
"""

from abc import ABC, abstractmethod
from logging import getLogger

from infrahouse_core.aws import get_client

LOG = getLogger(__name__)


class AWSResource(ABC):
    """Abstract base class for AWS resource wrappers.

    Subclasses must implement the :attr:`exists` property and the
    :meth:`delete` method.  The constructor provides a lazy-loaded
    boto3 client via :attr:`_client`.

    :param resource_id: Primary identifier for the resource (ID, name, ARN, etc.).
    :param service_name: AWS service name passed to ``get_client()``
        (e.g. ``"ec2"``, ``"dynamodb"``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    :param session: Pre-configured ``boto3.Session``.  When provided the
        client is created from this session instead of via :func:`get_client`.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, resource_id, service_name, region=None, role_arn=None, session=None
    ):
        self._resource_id = resource_id
        self._service_name = service_name
        self._region = region
        self._role_arn = role_arn
        self._session = session
        self._client_instance = None

    @property
    def _client(self):
        """Lazy-loaded boto3 client via :func:`get_client`."""
        if self._client_instance is None:
            if self._session is not None:
                self._client_instance = self._session.client(self._service_name, region_name=self._region)
            else:
                self._client_instance = get_client(
                    self._service_name,
                    region=self._region,
                    role_arn=self._role_arn,
                )
            LOG.debug(
                "Created %s client in %s region",
                self._service_name,
                self._client_instance.meta.region_name,
            )
        return self._client_instance

    @property
    @abstractmethod
    def exists(self) -> bool:
        """Check whether the resource currently exists.

        :return: ``True`` if the resource exists, ``False`` otherwise.
        """

    @abstractmethod
    def delete(self) -> None:
        """Delete the resource."""

    # -- Tag helpers ---------------------------------------------------------
    #
    # The default implementations use the AWS-wide generic tagging API
    # (``list_tags_for_resource`` / ``tag_resource`` / ``untag_resource``),
    # which covers CloudWatch Logs, RDS, Lambda, KMS, Secrets Manager, SNS,
    # SQS, Step Functions, and many other services.  Subclasses whose
    # service uses a different tag API (EC2 ``create_tags``, S3
    # ``put_bucket_tagging``, IAM ``tag_role``, etc.) should override these
    # methods.  All subclasses that want tag support must implement
    # :attr:`arn`.

    @property
    def arn(self) -> str:
        """Return the ARN of this resource.

        Subclasses must override this to enable the generic tag helpers.

        :raises NotImplementedError: if the subclass has not implemented ``arn``.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement arn")

    @property
    def tags(self) -> dict:
        """Return current tags as a ``{key: value}`` dict.

        Uses the generic ``list_tags_for_resource`` API.  Override in
        subclasses whose service uses a different tagging API.
        """
        response = self._client.list_tags_for_resource(resourceArn=self.arn)
        return response.get("tags", {})

    def set_tag(self, key: str, value: str) -> bool:
        """Set a single tag on this resource.

        Idempotent: if the tag is already set to ``value``, no API call is
        made.

        :param key: Tag key.
        :param value: Tag value.
        :returns: ``True`` if the tag was written, ``False`` if it was
            already current.
        """
        if self.tags.get(key) == value:
            return False
        self._client.tag_resource(resourceArn=self.arn, tags={key: value})
        LOG.info("Set tag %s=%s on %s", key, value, self.arn)
        return True

    def set_tags(self, tags: dict) -> int:
        """Set multiple tags on this resource.

        Idempotent: tags that already have the requested value are skipped.

        :param tags: Mapping of tag keys to values.
        :returns: Number of tags actually written.
        """
        current = self.tags
        to_write = {k: v for k, v in tags.items() if current.get(k) != v}
        if not to_write:
            return 0
        self._client.tag_resource(resourceArn=self.arn, tags=to_write)
        LOG.info("Set %d tag(s) on %s", len(to_write), self.arn)
        return len(to_write)

    def remove_tag(self, key: str) -> bool:
        """Remove a single tag from this resource.

        Idempotent: no-op if the tag is not currently set.

        :param key: Tag key to remove.
        :returns: ``True`` if the tag was present and removed, ``False``
            if it was already absent.
        """
        if key not in self.tags:
            return False
        self._client.untag_resource(resourceArn=self.arn, tagKeys=[key])
        LOG.info("Removed tag %s from %s", key, self.arn)
        return True
