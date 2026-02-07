"""
CloudFront Distribution resource wrapper.

Provides ``exists`` / ``delete()`` support for Amazon CloudFront
distributions.  Deletion is a multi-step process:

1. Disable the distribution (if enabled).
2. Wait for the distribution to reach the ``Deployed`` state.
3. Delete the distribution using the current ETag.
"""

from __future__ import annotations

import time
from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource
from infrahouse_core.timeout import timeout

LOG = getLogger(__name__)

# How long to sleep between status polls while waiting for deployment.
_POLL_INTERVAL_SECONDS = 30

# Maximum time (seconds) to wait for deployment before giving up.
_MAX_WAIT_SECONDS = 1800  # 30 minutes


class CloudFrontDistribution(AWSResource):
    """Wrapper around an Amazon CloudFront distribution.

    :param distribution_id: The CloudFront distribution ID (e.g. ``E1A2B3C4D5E6F7``).
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, distribution_id, region=None, role_arn=None):
        super().__init__(distribution_id, "cloudfront", region=region, role_arn=role_arn)

    @property
    def distribution_id(self) -> str:
        """Return the distribution ID.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the distribution exists.

        Returns ``False`` if the API raises ``NoSuchDistribution``.
        """
        try:
            self._client.get_distribution(Id=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchDistribution":
                return False
            raise

    # -- Enable / Disable -----------------------------------------------------

    def enable(self) -> None:
        """Enable the distribution.

        No-op if the distribution is already enabled.

        :raises ClientError: For unexpected AWS API errors.
        """
        self._set_enabled(True)

    def disable(self) -> None:
        """Disable the distribution.

        No-op if the distribution is already disabled.

        :raises ClientError: For unexpected AWS API errors.
        """
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        """Set the ``Enabled`` flag on the distribution config.

        :param enabled: ``True`` to enable, ``False`` to disable.
        """
        config_response = self._client.get_distribution_config(Id=self._resource_id)
        config = config_response["DistributionConfig"]
        etag = config_response["ETag"]

        if config["Enabled"] is enabled:
            LOG.info(
                "CloudFront distribution %s is already %s.",
                self._resource_id,
                "enabled" if enabled else "disabled",
            )
            return

        config["Enabled"] = enabled
        self._client.update_distribution(
            DistributionConfig=config,
            Id=self._resource_id,
            IfMatch=etag,
        )
        LOG.info(
            "%s CloudFront distribution %s",
            "Enabled" if enabled else "Disabled",
            self._resource_id,
        )

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Disable (if needed), wait for deployment, then delete the distribution.

        Idempotent -- does nothing if the distribution does not exist.

        :raises TimeoutError: If the distribution does not reach ``Deployed``
            status within the allowed wait time.
        :raises ClientError: For unexpected AWS API errors or if the
            distribution cannot be deleted (e.g. still in use).
        """
        try:
            self.disable()
        except ClientError as err:
            if err.response["Error"]["Code"] == "NoSuchDistribution":
                LOG.info("CloudFront distribution %s does not exist.", self._resource_id)
                return
            raise

        # Wait for the distribution to be fully deployed.
        self._wait_until_deployed()

        # Fetch the latest ETag and delete.
        #
        # Re-fetch because the ETag may have changed after the status
        # transition from InProgress → Deployed.
        config_response = self._client.get_distribution_config(Id=self._resource_id)
        etag = config_response["ETag"]

        self._client.delete_distribution(Id=self._resource_id, IfMatch=etag)
        LOG.info("Deleted CloudFront distribution %s", self._resource_id)

    def _wait_until_deployed(self) -> None:
        """Poll ``get_distribution`` until the status is ``Deployed``.

        :raises TimeoutError: If the status does not reach ``Deployed``
            within :data:`_MAX_WAIT_SECONDS`.
        """
        with timeout(_MAX_WAIT_SECONDS):
            while True:
                response = self._client.get_distribution(Id=self._resource_id)
                status = response["Distribution"]["Status"]
                if status == "Deployed":
                    return
                LOG.debug(
                    "Distribution %s status: %s — waiting %ds",
                    self._resource_id,
                    status,
                    _POLL_INTERVAL_SECONDS,
                )
                time.sleep(_POLL_INTERVAL_SECONDS)
