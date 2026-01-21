import logging
import uuid

import boto3
import pytest

LOG = logging.getLogger()

DYNAMODB_REGION = "us-west-1"


@pytest.fixture
def dynamodb_table():
    """
    Create a temporary DynamoDB table for integration testing.

    Yields (table_name, region) tuple, then deletes the table after the test.
    """
    table_name = f"test-lock-table-{uuid.uuid4().hex[:8]}"
    dynamodb = boto3.client("dynamodb", region_name=DYNAMODB_REGION)

    # Create table
    dynamodb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "ResourceId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "ResourceId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # Wait for table to be active
    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(TableName=table_name)

    LOG.info("Created DynamoDB table: %s", table_name)

    yield table_name, DYNAMODB_REGION

    # Cleanup: delete table
    dynamodb.delete_table(TableName=table_name)
    LOG.info("Deleted DynamoDB table: %s", table_name)
