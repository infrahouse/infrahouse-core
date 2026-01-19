from unittest import mock

from infrahouse_core.aws.ec2_instance import EC2Instance


def test_add_tag():
    mock_client = mock.Mock()
    instance_id = "i-1234567890abcdef0"

    with mock.patch.object(EC2Instance, "ec2_client", new_callable=mock.PropertyMock, return_value=mock_client):
        instance = EC2Instance(instance_id=instance_id)
        instance.add_tag("foo", "bar")
        mock_client.create_tags.assert_called_once_with(Resources=[instance_id], Tags=[{"Key": "foo", "Value": "bar"}])
