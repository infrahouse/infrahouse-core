"""
Module for DynamoDB class.
"""

import contextlib
from logging import getLogger
from time import sleep, time

import boto3
from botocore.exceptions import ClientError

LOG = getLogger(__name__)


class DynamoDBTable:
    """
    :param table_name: DynamoDB table name. It must exist.
    :type table_name: str
    """

    def __init__(self, table_name: str, region: str = None):
        self._table_name = table_name
        self._region = region
        self.__table = None

    def delete_item(self, **kwargs):
        """Delete record from the table."""
        self._table().delete_item(**kwargs)

    @contextlib.contextmanager
    def lock(self, lock_name: str, timeout: int = 30):
        """Global exclusive lock context manager.

        This function attempts to acquire a lock on a specific resource in the
        DynamoDB table using a conditional put operation. If the lock is acquired,
        the code within the 'with' block will execute. The lock is released after
        the block execution.

        :param lock_name: The name of the lock (resource) to be acquired.
        :param timeout: Maximum time in seconds to attempt acquiring the lock.
        :raises RuntimeError: If the lock cannot be acquired within the timeout.
        :raises ClientError: If an unexpected error occurs while trying to acquire the lock.
        """
        now = time()
        while True:
            if time() > now + timeout:
                raise RuntimeError(f"Failed to lock DNS lock table after {timeout} seconds")

            try:
                # Attempt to acquire the lock by adding an item with a conditional expression
                self.put_item(
                    Item={"ResourceId": lock_name},
                    ConditionExpression="attribute_not_exists(#r)",
                    ExpressionAttributeNames={"#r": "ResourceId"},
                )
                # Lock acquired successfully
                break
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    # Lock is already held by another process, retry after a short delay
                    sleep(1)
                else:
                    # An unexpected error occurred, propagate the exception
                    raise
        try:
            yield
        finally:
            # Release the lock by deleting the item
            self.delete_item(Key={"ResourceId": lock_name})

    def put_item(self, **kwargs):
        """Add record to the table."""
        self._table().put_item(**kwargs)

    def _table(self):
        if self.__table is None:
            self.__table = boto3.resource("dynamodb", region_name=self._region).Table(self._table_name)

        return self.__table
