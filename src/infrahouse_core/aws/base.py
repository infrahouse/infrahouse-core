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
