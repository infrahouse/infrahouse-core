"""Top level exceptions.

The exception hierarchy repeats the structure of the infrahouse_core package.
Each module in the package has its own exceptions.py module.
The module exceptions are inherited from the upper module exceptions.

"""

from infrahouse_core.exceptions import IHCoreException


class IHAWSException(IHCoreException):
    """AWS related InfraHouse exception"""


class IHDynamoDBException(IHAWSException):
    """DynamoDB related InfraHouse exception"""


class IHItemNotFound(IHDynamoDBException):
    """Requested DynamoDB item doesn't exist"""


class IHSecretsManagerException(IHAWSException):
    """Secrets Manager related InfraHouse exception"""


class IHSecretNotFound(IHSecretsManagerException):
    """Requested secret doesn't exist"""
