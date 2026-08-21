"""
Module for EC2Instance class - a class tha represents an EC2 instance.
"""

import re
import warnings
from enum import Enum
from logging import getLogger
from time import monotonic, sleep
from typing import Optional

from boto3 import Session
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from cached_property import cached_property_with_ttl
from ec2_metadata import ec2_metadata

from infrahouse_core.aws import get_client
from infrahouse_core.aws.exceptions import (
    IHBootstrapFailed,
    IHBootstrapTimeout,
    IHBootstrapUnknown,
)
from infrahouse_core.timeout import timeout
from infrahouse_core.validation import (
    validate_instance_id,
    validate_region,
    validate_role_arn,
)

LOG = getLogger(__name__)

# `cloud-init status` reports the state of the instance's own provisioning,
# whatever that provisioning is - an ih-bootstrap/Puppet instance, an ECS
# container instance, or a stock AMI. See EC2Instance.wait_for_bootstrap().
CLOUD_INIT_STATUS_COMMAND = "cloud-init status"

# Evidence to collect when bootstrap fails or times out. The instance is
# usually torn down right after, so this is the only chance to learn why.
CLOUD_INIT_DIAGNOSTIC_COMMANDS = (
    "cloud-init status --long",
    "tail -n 100 /var/log/cloud-init-output.log",
)


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

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        instance_id: str = None,
        region: str = None,
        ec2_client: Session = None,
        ssm_client: Session = None,
        role_arn: str = None,
        session: Session = None,
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
        :param role_arn: Use this IAM role to create boto3 clients.
        :type role_arn: str
        :param session: Pre-configured ``boto3.Session``.  When provided, clients are
            created from this session instead of via :func:`get_client`.
        :type session: boto3.Session
        """
        if ec2_client is not None:
            warnings.warn(
                "'ec2_client' is deprecated and will be removed in a future version. Pass role_arn instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        if ssm_client is not None:
            warnings.warn(
                "'ssm_client' is deprecated and will be removed in a future version. Pass role_arn instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # Validate input parameters
        validate_instance_id(instance_id)
        validate_region(region)
        validate_role_arn(role_arn)

        self._instance_id = instance_id
        self._region = region
        self._ec2_client = ec2_client
        self._ssm_client = ssm_client
        self._role_arn = role_arn
        self._session = session

    @property
    def availability_zone(self) -> str:
        """
        :return: Availability zone where this instance is hosted.
            This is obtained from EC2 metadata.
        """
        return ec2_metadata.availability_zone

    @property
    def cloud_init_status(self) -> str:
        """
        Provisioning state of the instance as reported by cloud-init itself.

        Known values are ``not run``, ``running``, ``done``, ``error`` and
        ``disabled``. Newer cloud-init versions also report ``degraded done``
        and ``degraded running``.

        :return: The cloud-init status, lowercased.
        :raise IHBootstrapUnknown: when the status can not be read from the
            instance, e.g. cloud-init is not installed on it.
        """
        exit_code, stdout, stderr = self.execute_command(CLOUD_INIT_STATUS_COMMAND)
        # `cloud-init status` exits non-zero when the status is `error` (1) or
        # `degraded done` (2), so a non-zero exit code is a state, not a failure.
        # Only an unparsable output means we could not learn the state.
        match = re.search(r"^status:\s*(\S.*?)\s*$", stdout, re.MULTILINE)
        if match is None:
            raise IHBootstrapUnknown(
                f"Could not parse `{CLOUD_INIT_STATUS_COMMAND}` output on {self.instance_id}. "
                f"Exit code: {exit_code}, STDOUT: {stdout!r}, STDERR: {stderr!r}"
            )
        return match.group(1).lower()

    @property
    def ec2_client(self) -> BaseClient:
        """
        Boto3 EC2 client.

        :return: Boto3 EC2 client.
        """
        if self._ec2_client is None:
            if self._session is not None:
                self._ec2_client = self._session.client("ec2", region_name=self._region)
            else:
                self._ec2_client = get_client("ec2", region=self._region, role_arn=self._role_arn)
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
        :return: Instance's private IP address.
            Can be None if the instance is in a transitional lifecycle state.
        """
        return self._describe_instance.get("PrivateIpAddress")

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
            if self._session is not None:
                self._ssm_client = self._session.client("ssm", region_name=self._region)
            else:
                self._ssm_client = get_client("ssm", region=self._region, role_arn=self._role_arn)
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

    @property
    def exists(self) -> bool:
        """
        Check whether the instance currently exists.

        An instance is considered non-existent if its state is
        ``terminated`` or ``shutting-down``, or if the describe call
        fails with ``InvalidInstanceID.NotFound``.

        :return: ``True`` if the instance exists and is not terminated.
        """
        try:
            return self.state not in ("terminated", "shutting-down")
        except ClientError as err:
            if err.response["Error"]["Code"] == "InvalidInstanceID.NotFound":
                return False
            raise

    def delete(self) -> None:
        """
        Terminate the EC2 instance.

        Idempotent — does nothing if the instance is already terminated
        or does not exist.
        """
        try:
            self.ec2_client.terminate_instances(InstanceIds=[self.instance_id])
            LOG.info("Terminated instance %s", self.instance_id)
        except ClientError as err:
            error_code = err.response["Error"]["Code"]
            if error_code == "InvalidInstanceID.NotFound":
                LOG.info("Instance %s does not exist.", self.instance_id)
            elif error_code == "OperationNotPermitted" and "terminated" in str(err).lower():
                LOG.info("Instance %s is already terminated.", self.instance_id)
            else:
                raise

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
        :return: A tuple containing the exit code, standard output, and standard error.

        Example::

            instance = EC2Instance("i-1234567890abcdef0", region="us-east-1")
            exit_code, stdout, stderr = instance.execute_command("hostname")
            if exit_code != 0:
                raise RuntimeError(f"Command failed: {stderr}")
        """
        command_id = self._send_command(command, send_timeout)
        return self._wait_for_command(command_id, execution_timeout)

    def wait_for_bootstrap(self, timeout_seconds: int = 600, poll_interval: int = 10) -> None:
        """
        Block until the instance finishes provisioning itself.

        The check is what cloud-init says about its own run, so it does not
        depend on **how** the instance is provisioned. On an instance built by
        terraform-aws-cloud-init, cloud-init reports ``done`` only after
        ih-bootstrap - and therefore ``ih-puppet apply`` - succeeded, because
        the bootstrap script runs from ``runcmd`` under ``set -euo pipefail``.
        An ECS container instance, or any other AMI, is covered by the same
        check without a special case.

        Note that cloud-init runs on every boot, so the answer is about the
        current boot.

        :param timeout_seconds: How long to wait for cloud-init to finish.
        :type timeout_seconds: int
        :param poll_interval: How long to wait between two status checks.
        :type poll_interval: int
        :raise IHBootstrapFailed: when cloud-init finishes with an error.
        :raise IHBootstrapTimeout: when cloud-init is still running after
            ``timeout_seconds`` seconds.
        :raise IHBootstrapUnknown: when the cloud-init status can not be read.

        The ``IHBootstrapFailed`` and ``IHBootstrapTimeout`` messages carry
        ``cloud-init status --long`` and a tail of
        ``/var/log/cloud-init-output.log`` collected from the instance.
        """
        # A deadline rather than the timeout() context manager on purpose:
        # timeout() is SIGALRM based and execute_command() uses it internally,
        # so the inner alarm would cancel the outer one and the wait would
        # never expire.
        deadline = monotonic() + timeout_seconds
        while True:
            status = self.cloud_init_status
            # `degraded done` is a completed run with a recoverable error,
            # `degraded running` is still in progress.
            if status.endswith("done"):
                if status != "done":
                    LOG.warning("cloud-init on %s finished as '%s'.", self.instance_id, status)
                LOG.info("Instance %s finished bootstrapping.", self.instance_id)
                return

            if status.endswith("error"):
                raise IHBootstrapFailed(
                    f"cloud-init on {self.instance_id} finished as '{status}'.\n{self._bootstrap_diagnostics()}"
                )

            if status == "disabled":
                LOG.warning("cloud-init is disabled on %s. There is nothing to wait for.", self.instance_id)
                return

            if monotonic() >= deadline:
                raise IHBootstrapTimeout(
                    f"cloud-init on {self.instance_id} is still '{status}' after {timeout_seconds} seconds.\n"
                    f"{self._bootstrap_diagnostics()}"
                )

            LOG.info("cloud-init on %s is '%s'. Waiting %d seconds.", self.instance_id, status, poll_interval)
            sleep(poll_interval)

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

    def _bootstrap_diagnostics(self, send_timeout: int = 30, execution_timeout: int = 30) -> str:
        """
        Collect cloud-init evidence from the instance.

        Best effort by design: this runs on a path that is already failing,
        often because SSM can not reach the instance at all. A command that
        fails here must not replace the failure it is meant to explain, and
        the short timeouts keep it from waiting as long as the caller just did.

        :param send_timeout: Time in seconds to attempt to send a command.
        :type send_timeout: int
        :param execution_timeout: Time in seconds to wait for a command to complete.
        :type execution_timeout: int
        :return: The collected output, ready to be embedded in an exception message.
        """
        report = []
        for command in CLOUD_INIT_DIAGNOSTIC_COMMANDS:
            try:
                _, stdout, stderr = self.execute_command(
                    command, send_timeout=send_timeout, execution_timeout=execution_timeout
                )
                report.append(f"$ {command}\n{stdout}{stderr}")
            except (ClientError, RuntimeError, TimeoutError) as err:
                LOG.warning("Could not collect `%s` from %s: %s", command, self.instance_id, err)
                report.append(f"$ {command}\n<unavailable: {err}>")
        return "\n".join(report)

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
                        # Check if the instance is terminated — no point retrying
                        state = self.state
                        if state in ("terminated", "shutting-down"):
                            raise RuntimeError(
                                f"Instance {self.instance_id} is {state} — SSM will never connect"
                            ) from e
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
