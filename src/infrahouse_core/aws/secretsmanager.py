"""
Module for Secret class - a class that represents an AWS Secrets Manager secret.
"""

import json
from logging import getLogger
from typing import Union

from botocore.exceptions import ClientError

from infrahouse_core.aws import get_client
from infrahouse_core.aws.exceptions import IHSecretNotFound

LOG = getLogger(__name__)


class Secret:
    """
    Secret represents an AWS Secrets Manager secret.

    :param secret_name: The name or ARN of the secret.
    :type secret_name: str
    :param region: AWS region. If omitted, uses the default region.
    :type region: str
    :param role_arn: IAM role ARN to assume for cross-account access.
    :type role_arn: str
    """

    def __init__(self, secret_name: str, region: str = None, role_arn: str = None):
        self._secret_name = secret_name
        self._region = region
        self._role_arn = role_arn
        self.__client = None

    def _client(self):
        """Lazily create and return the Secrets Manager client."""
        if self.__client is None:
            self.__client = get_client("secretsmanager", role_arn=self._role_arn, region=self._region)
        return self.__client

    @property
    def name(self) -> str:
        """
        Get the secret name.

        :return: The secret name as provided to the constructor.
        """
        return self._secret_name

    @property
    def exists(self) -> bool:
        """
        Check if the secret exists.

        :return: True if the secret exists, False otherwise.
        :raises ClientError: If an unexpected AWS error occurs.
        """
        try:
            self._client().describe_secret(SecretId=self._secret_name)
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    @property
    def value(self) -> Union[dict, str]:
        """
        Get the secret value.

        If the secret value is valid JSON, it is parsed and returned as a dict.
        Otherwise, the raw string is returned.

        Note: Binary secrets (SecretBinary) are not supported.

        :return: The secret value as a dict (if JSON) or string.
        :raises IHSecretNotFound: If the secret does not exist.
        :raises ClientError: If an unexpected AWS error occurs.
        """
        try:
            response = self._client().get_secret_value(SecretId=self._secret_name)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                raise IHSecretNotFound(f"Secret not found: {self._secret_name}") from err
            raise

        secret_string = response["SecretString"]
        try:
            return json.loads(secret_string)
        except json.JSONDecodeError:
            return secret_string

    @property
    def arn(self) -> str:
        """
        Get the ARN of the secret.

        :return: The secret ARN.
        :raises IHSecretNotFound: If the secret does not exist.
        :raises ClientError: If an unexpected AWS error occurs.
        """
        try:
            response = self._client().describe_secret(SecretId=self._secret_name)
            return response["ARN"]
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                raise IHSecretNotFound(f"Secret not found: {self._secret_name}") from err
            raise

    @property
    def version_id(self) -> str:
        """
        Get the current version ID of the secret.

        :return: The version ID.
        :raises IHSecretNotFound: If the secret does not exist.
        :raises ClientError: If an unexpected AWS error occurs.
        """
        try:
            response = self._client().get_secret_value(SecretId=self._secret_name)
            return response["VersionId"]
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                raise IHSecretNotFound(f"Secret not found: {self._secret_name}") from err
            raise

    def create(self, value: Union[dict, str], description: str = None):
        """
        Create the secret.

        :param value: The secret value. If a dict, it will be JSON-encoded.
        :type value: Union[dict, str]
        :param description: Optional description for the secret.
        :type description: str
        :raises ClientError: If an AWS error occurs (e.g., secret already exists).
        """
        secret_string = json.dumps(value) if isinstance(value, dict) else value
        kwargs = {
            "Name": self._secret_name,
            "SecretString": secret_string,
        }
        if description:
            kwargs["Description"] = description
        self._client().create_secret(**kwargs)
        LOG.info("Created secret %s", self._secret_name)

    def update(self, value: Union[dict, str]):
        """
        Update the secret value.

        :param value: The new secret value. If a dict, it will be JSON-encoded.
        :type value: Union[dict, str]
        :raises IHSecretNotFound: If the secret does not exist.
        :raises ClientError: If an unexpected AWS error occurs.
        """
        secret_string = json.dumps(value) if isinstance(value, dict) else value
        try:
            self._client().put_secret_value(SecretId=self._secret_name, SecretString=secret_string)
            LOG.info("Updated secret %s", self._secret_name)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                raise IHSecretNotFound(f"Secret not found: {self._secret_name}") from err
            raise

    def delete(self, force: bool = False, recovery_window_days: int = None):
        """
        Delete the secret.

        :param force: If True, delete immediately without recovery window.
        :type force: bool
        :param recovery_window_days: Days before permanent deletion (7-30).
            Ignored if force=True.
        :type recovery_window_days: int
        :raises IHSecretNotFound: If the secret does not exist.
        :raises ClientError: If an unexpected AWS error occurs.
        """
        kwargs = {"SecretId": self._secret_name}
        if force:
            kwargs["ForceDeleteWithoutRecovery"] = True
        elif recovery_window_days is not None:
            kwargs["RecoveryWindowInDays"] = recovery_window_days

        try:
            self._client().delete_secret(**kwargs)
            LOG.info("Deleted secret %s", self._secret_name)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceNotFoundException":
                raise IHSecretNotFound(f"Secret not found: {self._secret_name}") from err
            raise

    def ensure_present(self, value: Union[dict, str], description: str = None, update_if_exists: bool = False):
        """
        Ensure the secret exists, creating it if necessary.

        :param value: The secret value. If a dict, it will be JSON-encoded.
        :type value: Union[dict, str]
        :param description: Optional description for the secret.
        :type description: str
        :param update_if_exists: If True, update the secret value if it already exists.
        :type update_if_exists: bool
        :raises ClientError: If an unexpected AWS error occurs.
        """
        try:
            self.create(value, description=description)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ResourceExistsException":
                if update_if_exists:
                    self.update(value)
                return
            raise

    def ensure_absent(self, force: bool = False, recovery_window_days: int = None):
        """
        Ensure the secret does not exist, deleting it if necessary.

        :param force: If True, delete immediately without recovery window.
        :type force: bool
        :param recovery_window_days: Days before permanent deletion (7-30).
            Ignored if force=True.
        :type recovery_window_days: int
        :raises ClientError: If an unexpected AWS error occurs.
        """
        try:
            self.delete(force=force, recovery_window_days=recovery_window_days)
        except IHSecretNotFound:
            pass  # Already gone, that's fine
