"""
EMR Serverless Application resource wrapper.

Provides ``exists`` / ``delete()`` support.  An EMR Serverless application
must be in ``CREATED`` or ``STOPPED`` state before it can be deleted.  If the
application is ``STARTED``, ``delete()`` will stop it first.
"""

from __future__ import annotations

from logging import getLogger
from time import sleep

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource
from infrahouse_core.timeout import timeout

LOG = getLogger(__name__)

_STOP_POLL_INTERVAL = 5
_STOP_TIMEOUT = 120


class EMRServerlessApplication(AWSResource):
    """Wrapper around an EMR Serverless application.

    :param application_id: Application identifier.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, application_id, region=None, role_arn=None, session=None):
        super().__init__(application_id, "emr-serverless", region=region, role_arn=role_arn, session=session)

    @property
    def application_id(self) -> str:
        """Return the application identifier.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the application exists and is not terminated.

        Returns ``False`` if the application is not found or its state is
        ``TERMINATED``.
        """
        try:
            response = self._client.get_application(applicationId=self._resource_id)
            return response["application"]["state"] != "TERMINATED"
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    def delete(self) -> None:
        """Delete the application.

        If the application is in ``STARTED`` state, it will be stopped first.
        Idempotent -- does nothing if the application does not exist.
        """
        try:
            response = self._client.get_application(applicationId=self._resource_id)
            state = response["application"]["state"]
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                LOG.info("EMR Serverless application %s does not exist.", self._resource_id)
                return
            raise

        if state == "STARTED":
            LOG.info("Stopping EMR Serverless application %s before deletion", self._resource_id)
            self._client.stop_application(applicationId=self._resource_id)
            self._wait_for_stopped()

        try:
            self._client.delete_application(applicationId=self._resource_id)
            LOG.info("Deleted EMR Serverless application %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                LOG.info("EMR Serverless application %s does not exist.", self._resource_id)
            else:
                raise

    def _wait_for_stopped(self) -> None:
        """Poll until the application reaches ``STOPPED`` state."""
        with timeout(_STOP_TIMEOUT):
            while True:
                response = self._client.get_application(applicationId=self._resource_id)
                state = response["application"]["state"]
                if state == "STOPPED":
                    return
                LOG.debug("Application %s state: %s -- waiting %ds", self._resource_id, state, _STOP_POLL_INTERVAL)
                sleep(_STOP_POLL_INTERVAL)
