"""Top level exceptions.

The exception hierarchy repeats the structure of the infrahouse_core package.
Each module in the package has its own exceptions.py module.
The module exceptions are inherited from the upper module exceptions.

"""

from infrahouse_core.aws import IHAWSException


class IHRoute53Exception(IHAWSException):
    """Route53 related InfraHouse exception"""


class IHZoneNotFound(IHRoute53Exception):
    """Requested Route53 zone doesn't exist"""


class IHRecordNotFound(IHRoute53Exception):
    """Requested Route53 record doesn't exist"""
