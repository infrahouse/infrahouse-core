from unittest import mock

from infrahouse_core.aws.ec2_instance import EC2Instance


def test_describe_instance():
    instance_id = "i-1234567890abcdef0"
    with mock.patch("infrahouse_core.aws.ec2_instance.get_client") as mock_client:
        assert EC2Instance(instance_id=instance_id)._describe_instance
        mock_client.assert_called_once_with("ec2", region=None, role_arn=None)


def test_describe_instance_with_client():
    instance_id = "i-1234567890abcdef0"
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

    assert EC2Instance(instance_id=instance_id, ec2_client=mock_client)._describe_instance
    mock_client.describe_instances.assert_called_once_with(InstanceIds=[instance_id])
