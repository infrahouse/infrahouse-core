from unittest import mock

from infrahouse_core.aws.ec2_instance import EC2Instance


def test_add_tag():
    mock_client = mock.Mock()

    with mock.patch.object(EC2Instance, "ec2_client", new_callable=mock.PropertyMock, return_value=mock_client):
        instance = EC2Instance(instance_id="i-aaa")
        instance.add_tag("foo", "bar")
        mock_client.create_tags.assert_called_once_with(Resources=["i-aaa"], Tags=[{"Key": "foo", "Value": "bar"}])
