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
    def lock(self, lock_name, timeout: int = 30):
        """Global exclusive lock.

        Usage: \b

        t = DynamoDBTable("update-dns-BIcLL4ROdNyC15hzy1Ku")
        with t.lock("foo"):
            print("hello")

        """
        now = time()
        while True:
            if time() > now + timeout:
                raise RuntimeError(f"Failed to lock DNS lock table after {timeout} seconds")

            try:
                # Put item with conditional expression to acquire the lock
                self.put_item(
                    Item={"ResourceId": lock_name},
                    ConditionExpression="attribute_not_exists(#r)",
                    ExpressionAttributeNames={"#r": "ResourceId"},
                )
                # Lock acquired
                break
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    # Else, lock cannot be acquired because already locked
                    sleep(1)
                # Another exception than ConditionalCheckFailedException was caught, raise as-is
                else:
                    raise
        try:
            yield

        finally:
            self.delete_item(
                Key={
                    "ResourceId": lock_name,
                }
            )

    def put_item(self, **kwargs):
        """Add record to the table."""
        self._table().put_item(**kwargs)

    def _table(self):
        if self.__table is None:
            self.__table = boto3.resource("dynamodb", region_name=self._region).Table(self._table_name)

        return self.__table
