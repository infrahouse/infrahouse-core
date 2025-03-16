from unittest import mock

from infrahouse_core.aws.ec2_instance import EC2Instance


def test_describe_instance():
    with mock.patch("infrahouse_core.aws.ec2_instance.get_client") as mock_client:
        assert EC2Instance(instance_id="foo")._describe_instance
        mock_client.assert_called_once_with("ec2", region=None)


def test_describe_instance_with_client():
    mock_client = mock.Mock()
    mock_client.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "Tags": [
                            {"Key": "Name", "Value": "foo-instance"},
                        ],
                    }
                ],
            }
        ],
    }

    assert EC2Instance(instance_id="foo", ec2_client=mock_client)._describe_instance
    mock_client.describe_instances.assert_called_once_with(InstanceIds=["foo"])
