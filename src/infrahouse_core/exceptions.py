"""Top level exceptions.

The exception hierarchy repeats the structure of the infrahouse_core package.
Each module in the package has its own exceptions.py module.
The module exceptions are inherited from the upper module exceptions.

"""


class IHCoreException(Exception):
    """Generic InfraHouse Core exception"""
