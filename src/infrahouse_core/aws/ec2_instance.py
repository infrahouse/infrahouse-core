"""
Module for EC2Instance class - a class tha represents an EC2 instance.
"""

from enum import Enum
from logging import getLogger
from time import sleep
from typing import Optional

from boto3 import Session
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from cached_property import cached_property_with_ttl
from ec2_metadata import ec2_metadata

from infrahouse_core.aws import get_client
from infrahouse_core.timeout import timeout

LOG = getLogger()


class CommandStatus(Enum):
    """
    Enum representing possible command statuses for EC2 instance operations.

    Attributes:

        - ``PENDING``: The command is pending execution.
        - ``IN_PROGRESS``: The command is currently in progress.
        - ``DELAYED``: The command execution has been delayed.
        - ``SUCCESS``: The command executed successfully.
        - ``CANCELLED``: The command execution was cancelled.
        - ``TIMED_OUT``: The command execution has timed out.
        - ``FAILED``: The command execution failed.
        - ``CANCELLING``: The command is in the process of being cancelled.
    """

    PENDING = "Pending"
    IN_PROGRESS = "InProgress"
    DELAYED = "Delayed"
    SUCCESS = "Success"
    CANCELLED = "Cancelled"
    TIMED_OUT = "TimedOut"
    FAILED = "Failed"
    CANCELLING = "Cancelling"


class EC2Instance:
    """
    EC2Instance represents an EC2 instance.

    :param instance_id: Instance id. If omitted, the local instance is read from metadata.
    :type instance_id: str
    """

    def __init__(
        self, instance_id: str = None, region: str = None, ec2_client: Session = None, ssm_client: Session = None
    ):
        """
        :param instance_id: Instance id. If omitted, the local instance is read from metadata.
        :type instance_id: str
        :param region: AWS region to connect to. If omitted, the region is read from the instance metadata.
        :type region: str
        :param ec2_client: Boto3 EC2 client. If omitted, a client is created using the region and credentials.
        :type ec2_client: Session
        :param ssm_client: Boto3 SSM client. If omitted, a client is created using the region and credentials.
        :type ssm_client: Session
        """
        self._instance_id = instance_id
        self._region = region
        self._ec2_client = ec2_client
        self._ssm_client = ssm_client

    @property
    def availability_zone(self) -> str:
        """
        :return: Availability zone where this instance is hosted.
            This is obtained from EC2 metadata.
        """
        return ec2_metadata.availability_zone

    @property
    def ec2_client(self) -> BaseClient:
        """
        Boto3 EC2 client.

        :return: Boto3 EC2 client.
        """
        if self._ec2_client is None:
            self._ec2_client = get_client("ec2", region=self._region)
        return self._ec2_client

    @property
    def instance_id(self) -> str:
        """
        The instance's instance_id. It's read from metadata
        if the class instance was created w/o specifying it.

        :return: The instance's instance_id.
        """
        if self._instance_id is None:
            # If the instance_id was not given, obtain it from metadata
            self._instance_id = ec2_metadata.instance_id
        return self._instance_id

    @property
    def hostname(self) -> Optional[str]:
        """
        :return: Instance's private hostname, i.e. the first part of the private DNS name.
            For example, if the private DNS name is ip-10-0-0-1.eu-west-1.compute.internal,
            the hostname is ip-10-0-0-1.
        """
        return self.private_dns_name.split(".")[0] if self.private_dns_name else None

    @property
    def private_dns_name(self):
        """
        :return: Instance's private DNS name.
            This name is for use inside the VPC and is not accessible from the
            public Internet.
        """
        return self._describe_instance["PrivateDnsName"]

    @property
    def private_ip(self):
        """
        :return: Instance's private IP address
        """
        return self._describe_instance["PrivateIpAddress"]

    @property
    def public_ip(self):
        """
        :return: Instance's public IP address.
            Can be None if the instance is not configured to have a public IP.
        """
        return self._describe_instance.get("PublicIpAddress")

    @property
    def ssm_client(self) -> BaseClient:
        """
        Boto3 SSM client.

        :return: Boto3 SSM client.
        """
        if self._ssm_client is None:
            self._ssm_client = get_client("ssm", region=self._region)
        return self._ssm_client

    @property
    def state(self) -> str:
        """
        :return: The state of the instance.
            Can be one of the following values:
            - ``pending``: The instance is preparing to launch.
            - ``running``: The instance is running and ready for use.
            - ``shutting-down``: The instance is preparing to be terminated.
            - ``terminated``: The instance has been shut down.
            - ``stopping``: The instance is stopping.
            - ``stopped``: The instance has been stopped.
        """
        return self._describe_instance["State"]["Name"]

    @property
    def tags(self) -> dict:
        """
        :return: A dictionary with the instance tags. Keys are tag names, and values - the tag values.
        """
        # Tags are returned as a list of dictionaries, where each dictionary has 'Key' and 'Value' keys.
        # We want to expose them as a dictionary, where the key is the tag name and the value - the tag value.
        return {tag["Key"]: tag["Value"] for tag in self._describe_instance["Tags"]}

    def add_tag(self, key: str, value: str):
        """
        Add a tag to the EC2 instance.

        :param key: The key of the tag.
        :type key: str
        :param value: The value of the tag.
        :type value: str
        """
        self.ec2_client.create_tags(
            Resources=[
                self.instance_id,
            ],
            Tags=[
                {
                    "Key": key,
                    "Value": value,
                },
            ],
        )

    def execute_command(
        self, command: str, send_timeout: int = 600, execution_timeout: int = 60
    ) -> tuple[int, str, str]:
        """
        Execute a command on the EC2 instance via SSM.

        :param command: The command to execute.
        :type command: str
        :param send_timeout: Time in seconds to attempt to send a command.
            Instances coming back from hibernation may take about 5 minutes.
        :type send_timeout: int
        :param execution_timeout: Time in seconds to wait for the command to complete.
        :type execution_timeout: int
        :return: A tuple containing the command ID, standard output, and standard error.
        """
        command_id = self._send_command(command, send_timeout)
        return self._wait_for_command(command_id, execution_timeout)

    @cached_property_with_ttl(ttl=10)
    def _describe_instance(self):
        """
        Describe the instance - fetch instance data from AWS.

        :return: A dictionary with the instance data as returned by the
            ``describe_instances`` method of the EC2 client.
        """
        return self.ec2_client.describe_instances(
            InstanceIds=[
                self.instance_id,
            ],
        )[
            "Reservations"
        ][0][
            "Instances"
        ][0]

    def _send_command(self, command: str, send_timeout: int = 600) -> str:
        """
        Send a command to the instance via SSM, retrying with exponential backoff
        if the instance is not ready (indicated by an 'InvalidInstanceId' error).

        The method will retry up to a maximum number of attempts before raising a TimeoutError.

        :param command: The command to send.
        :type command: str
        :param send_timeout: Time in seconds to attempt to send a command.
            Instances coming back from hibernation may take about 5 minutes.
        :type send_timeout: int
        :return: The command ID of the sent command.
        """
        delay = 3  # initial delay in seconds
        with timeout(send_timeout):  # it takes about 5 minutes to wake SSM agent
            while True:
                try:
                    # If the instance is not ready yet, the SSM client will raise an
                    # InvalidInstanceId error. We catch this error and retry until
                    # the instance is ready.
                    response = self.ssm_client.send_command(
                        InstanceIds=[self.instance_id],
                        DocumentName="AWS-RunShellScript",
                        Parameters={"commands": [command]},
                    )
                    command_id = response["Command"]["CommandId"]
                    LOG.info("Command sent. ID: %s", command_id)
                    return command_id

                except ClientError as e:
                    if e.response["Error"]["Code"] == "InvalidInstanceId":
                        LOG.warning("Instance is not ready yet. Retrying in %d seconds.", delay)
                        sleep(delay)
                        delay = min(delay * 2, 30)  # increase delay exponentially, capped at 30 seconds
                        continue

                    raise  # Re-raise other unexpected exceptions

    def _wait_for_command(self, command_id: str, execution_timeout: int = 60) -> tuple[int, str, str]:
        """
        Wait for the command to finish and return the exit code, standard output,
        and standard error.

        The method will retry up to a maximum number of attempts before raising a TimeoutError.

        :param command_id: The command ID of the sent command.
        :type command_id: str
        :param execution_timeout: Time in seconds to wait for the command to finish.
        :type execution_timeout: int
        :return: A tuple containing the exit code, standard output, and standard error.
        """
        delay = 1  # initial delay in seconds
        # Wait for the command to finish
        with timeout(execution_timeout):
            while True:
                try:
                    invocation = self.ssm_client.get_command_invocation(
                        CommandId=command_id,
                        InstanceId=self.instance_id,
                    )
                    status = invocation["Status"]
                    LOG.info("Current status: %s", status)

                    if CommandStatus(status) in [
                        CommandStatus.SUCCESS,
                        CommandStatus.FAILED,
                        CommandStatus.TIMED_OUT,
                        CommandStatus.CANCELLED,
                    ]:
                        # Check exit code and output
                        exit_code = int(invocation["ResponseCode"])
                        stdout = invocation["StandardOutputContent"]
                        stderr = invocation["StandardErrorContent"]

                        LOG.debug("Exit code: %d", exit_code)

                        if exit_code != 0:
                            LOG.error("Command failed with exit code %d", exit_code)

                        getattr(LOG, "error" if exit_code != 0 else "debug")("STDOUT:\n%s", stdout)
                        getattr(LOG, "error" if exit_code != 0 else "debug")("STDERR:\n%s", stderr)
                        return exit_code, stdout, stderr

                    sleep(delay)
                    delay = min(delay * 2, 30)  # increase delay exponentially, capped at 30 seconds

                except ClientError as e:
                    if e.response["Error"]["Code"] == "InvocationDoesNotExist":
                        LOG.warning("Invocation not yet available. Retrying.")
                        sleep(0.1)
                        continue

                    raise  # Re-raise other unexpected exceptions
