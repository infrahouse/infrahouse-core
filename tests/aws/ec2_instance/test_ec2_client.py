from unittest.mock import Mock

from infrahouse_core.aws.ec2_instance import EC2Instance


def test_ec2_client():

    mock_client = Mock()
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

    instance = EC2Instance("foo", ec2_client=mock_client)
    assert instance.tags == {"Name": "foo-instance"}
    mock_client.describe_instances.assert_called_once_with(InstanceIds=["foo"])
