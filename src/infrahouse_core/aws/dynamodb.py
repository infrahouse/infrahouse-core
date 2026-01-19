"""
Module for DynamoDB class.
"""

import contextlib
from logging import getLogger
from time import sleep, time

from botocore.exceptions import ClientError

from infrahouse_core.aws import get_resource
from infrahouse_core.aws.exceptions import IHItemNotFound

LOG = getLogger(__name__)


class DynamoDBTable:
    """
    DynamoDB table wrapper with distributed locking support.

    :param table_name: DynamoDB table name. It must exist.
    :type table_name: str
    :param region: AWS region
    :type region: str
    :param role_arn: IAM role ARN to assume for cross-account access.
    :type role_arn: str
    """

    def __init__(self, table_name: str, region: str = None, role_arn: str = None):
        self._table_name = table_name
        self._region = region
        self._role_arn = role_arn
        self._table_instance = None

    def delete_item(self, **kwargs):
        """Delete record from the table."""
        self._table().delete_item(**kwargs)

    def get_item(self, **kwargs) -> dict:
        """Get a record from the table.

        :param kwargs: Arguments passed to boto3 DynamoDB get_item().
            Key (required): Primary key of the item to retrieve.
        :return: The item attributes as a dictionary.
        :raises IHItemNotFound: If the item does not exist.
        """
        response = self._table().get_item(**kwargs)
        item = response.get("Item")
        if item is None:
            raise IHItemNotFound(f"Item not found in '{self._table_name}': {kwargs.get('Key')}")
        return item

    @contextlib.contextmanager
    def lock(self, lock_name: str, timeout: int = 30, key_name: str = "ResourceId"):
        """Global exclusive lock context manager.

        This function attempts to acquire a lock on a specific resource in the
        DynamoDB table using a conditional put operation. If the lock is acquired,
        the code within the 'with' block will execute. The lock is released after
        the block execution.

        :param lock_name: The name of the lock (resource) to be acquired.
        :param timeout: Maximum time in seconds to attempt acquiring the lock.
        :param key_name: The partition key name in the DynamoDB table (default: "ResourceId").
        :raises RuntimeError: If the lock cannot be acquired within the timeout.
        :raises ClientError: If an unexpected error occurs while trying to acquire the lock.
        """
        now = time()
        while True:
            if time() > now + timeout:
                raise RuntimeError(f"Failed to acquire lock '{lock_name}' after {timeout} seconds")

            try:
                self.put_item(
                    Item={key_name: lock_name},
                    ConditionExpression="attribute_not_exists(#r)",
                    ExpressionAttributeNames={"#r": key_name},
                )
                LOG.info("Lock acquired: %s", lock_name)
                break
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    LOG.debug("Lock busy, waiting...")
                    sleep(1)
                else:
                    raise
        try:
            yield
        finally:
            self.delete_item(Key={key_name: lock_name})
            LOG.info("Lock released: %s", lock_name)

    def put_item(self, **kwargs):
        """Add record to the table."""
        self._table().put_item(**kwargs)

    def _table(self):
        if self._table_instance is None:
            resource = get_resource("dynamodb", role_arn=self._role_arn, region=self._region)
            self._table_instance = resource.Table(self._table_name)
            LOG.debug("Created DynamoDB table resource for %s", self._table_name)
        return self._table_instance
