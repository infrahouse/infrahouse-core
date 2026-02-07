"""
ACM Certificate resource wrapper.

Provides ``exists`` / ``delete()`` support for AWS Certificate Manager
certificates.
"""

from __future__ import annotations

from logging import getLogger

from botocore.exceptions import ClientError

from infrahouse_core.aws.base import AWSResource

LOG = getLogger(__name__)


class ACMCertificate(AWSResource):
    """Wrapper around an ACM certificate.

    :param certificate_arn: ARN of the ACM certificate.
    :param region: AWS region.
    :param role_arn: IAM role ARN for cross-account access.
    """

    def __init__(self, certificate_arn, region=None, role_arn=None):
        super().__init__(certificate_arn, "acm", region=region, role_arn=role_arn)

    @property
    def certificate_arn(self) -> str:
        """Return the ARN of the certificate.

        :rtype: str
        """
        return self._resource_id

    @property
    def exists(self) -> bool:
        """Return ``True`` if the certificate exists.

        Returns ``False`` if the API raises ``ResourceNotFoundException``.
        """
        try:
            self._client.describe_certificate(CertificateArn=self._resource_id)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    # -- Delete --------------------------------------------------------------

    def delete(self) -> None:
        """Delete the ACM certificate.

        Idempotent -- does nothing if the certificate does not exist.

        .. note::

            ``ResourceInUseException`` is **not** caught and will propagate
            to the caller.  The certificate must be disassociated from all
            AWS services (CloudFront, ELB, etc.) before deletion.
        """
        try:
            self._client.delete_certificate(CertificateArn=self._resource_id)
            LOG.info("Deleted ACM certificate %s", self._resource_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                LOG.info("ACM certificate %s does not exist.", self._resource_id)
            else:
                raise
