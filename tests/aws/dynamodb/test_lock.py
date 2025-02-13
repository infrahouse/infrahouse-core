from unittest import mock

from infrahouse_core.aws.dynamodb import DynamoDBTable


def test_lock():
    t = DynamoDBTable("foo-table")
    with (
        mock.patch.object(DynamoDBTable, "put_item") as mock_put,
        mock.patch.object(DynamoDBTable, "delete_item") as mock_delete,
    ):
        with t.lock("foo"):
            print("hello")

        mock_put.assert_called_once_with(
            Item={"ResourceId": "foo"},
            ConditionExpression="attribute_not_exists(#r)",
            ExpressionAttributeNames={"#r": "ResourceId"},
        )
        mock_delete.assert_called_once_with(Key={"ResourceId": "foo"})
