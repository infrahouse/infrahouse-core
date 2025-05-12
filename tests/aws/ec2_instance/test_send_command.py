import logging
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.ec2_instance import EC2Instance
from infrahouse_core.logging import setup_logging

LOG = logging.getLogger()
setup_logging(LOG, debug=True)


@pytest.fixture
def ec2_instance(monkeypatch):
    # Patch the sleep function in the module so tests run without delay.
    monkeypatch.setattr("infrahouse_core.aws.ec2_instance.sleep", lambda seconds: None)
    # Create an instance with dummy instance_id and region.
    instance = EC2Instance(instance_id="i-1234567890abcdef", region="us-east-1")
    # Override the ssm_client with a MagicMock to intercept calls.
    instance._ssm_client = MagicMock()
    return instance


def test_send_command_immediate_success(ec2_instance):
    # Simulate an immediate successful response from send_command.
    valid_response = {"Command": {"CommandId": "cmd-123456"}}
    ec2_instance._ssm_client.send_command.return_value = valid_response

    command_id = ec2_instance._send_command("echo hello")

    assert command_id == "cmd-123456"
    ec2_instance._ssm_client.send_command.assert_called_once_with(
        InstanceIds=["i-1234567890abcdef"], DocumentName="AWS-RunShellScript", Parameters={"commands": ["echo hello"]}
    )


def test_send_command_retry_then_success(ec2_instance):
    # Prepare a ClientError to simulate "InvalidInstanceId" on the first attempt.
    error_response = {"Error": {"Code": "InvalidInstanceId", "Message": "Instance not ready"}}
    client_error = ClientError(error_response, "send_command")
    valid_response = {"Command": {"CommandId": "cmd-654321"}}

    # Set side_effect: first call raises an error, second call returns a valid response.
    ec2_instance._ssm_client.send_command.side_effect = [client_error, valid_response]

    command_id = ec2_instance._send_command("echo retry")

    assert command_id == "cmd-654321"
    assert ec2_instance._ssm_client.send_command.call_count == 2


# def test_execute_command():
#     ec2_instance = EC2Instance()
#     exec_code, stdout, stderr = ec2_instance.execute_command("echo hello")
#     assert exec_code == 0
#     assert stdout == "hello\n"
#     assert stderr == ""
