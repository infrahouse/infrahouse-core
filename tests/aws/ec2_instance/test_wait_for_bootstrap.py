"""Tests for EC2Instance.cloud_init_status and EC2Instance.wait_for_bootstrap()."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.ec2_instance import EC2Instance
from infrahouse_core.aws.exceptions import (
    IHBootstrapFailed,
    IHBootstrapTimeout,
    IHBootstrapUnknown,
)

DIAGNOSTIC_OUTPUT = {
    "cloud-init status --long": "status: error\nerrors:\n\t- ih-bootstrap exited 1",
    "tail -n 100 /var/log/cloud-init-output.log": "Error: Could not apply the manifest",
}


@pytest.fixture(name="instance")
def _instance(monkeypatch):
    """An EC2Instance that never really sleeps."""
    monkeypatch.setattr("infrahouse_core.aws.ec2_instance.sleep", lambda seconds: None)
    return EC2Instance(instance_id="i-1234567890abcdef", region="us-east-1")


def _fake_execute_command(statuses):
    """
    Build an execute_command() replacement.

    :param statuses: cloud-init statuses to report, one per ``cloud-init status`` call.
        The last one is repeated if the caller polls more times than there are statuses.
    :type statuses: list
    :return: A function that can replace EC2Instance.execute_command.
    """
    remaining = list(statuses)

    def _execute_command(command, **_):
        if command == "cloud-init status":
            status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            return 0, f"status: {status}\n", ""
        return 0, DIAGNOSTIC_OUTPUT[command], ""

    return _execute_command


# -- cloud_init_status --------------------------------------------------------


def test_cloud_init_status(instance):
    """cloud_init_status returns the status cloud-init reports."""
    with mock.patch.object(EC2Instance, "execute_command", side_effect=_fake_execute_command(["running"])):
        assert instance.cloud_init_status == "running"


def test_cloud_init_status_is_lowercased(instance):
    """cloud_init_status normalizes the case."""
    with mock.patch.object(EC2Instance, "execute_command", return_value=(0, "status: Done\n", "")):
        assert instance.cloud_init_status == "done"


def test_cloud_init_status_unparsable(instance):
    """cloud_init_status raises when cloud-init is not on the instance."""
    with mock.patch.object(
        EC2Instance, "execute_command", return_value=(127, "", "bash: cloud-init: command not found")
    ):
        with pytest.raises(IHBootstrapUnknown) as exc_info:
            _ = instance.cloud_init_status
    assert "command not found" in str(exc_info.value)


# -- wait_for_bootstrap: success ----------------------------------------------


def test_wait_for_bootstrap_done(instance):
    """wait_for_bootstrap() returns as soon as cloud-init is done."""
    with mock.patch.object(
        EC2Instance, "execute_command", side_effect=_fake_execute_command(["done"])
    ) as mock_execute:
        instance.wait_for_bootstrap()
    # Done on the first check: no diagnostics, no second poll.
    assert mock_execute.call_count == 1


def test_wait_for_bootstrap_polls_until_done(instance):
    """wait_for_bootstrap() keeps polling while cloud-init is running."""
    with mock.patch.object(
        EC2Instance, "execute_command", side_effect=_fake_execute_command(["not run", "running", "running", "done"])
    ) as mock_execute:
        instance.wait_for_bootstrap()
    assert mock_execute.call_count == 4


def test_wait_for_bootstrap_degraded_done(instance):
    """A degraded but finished cloud-init run is not a failure."""
    with mock.patch.object(EC2Instance, "execute_command", side_effect=_fake_execute_command(["degraded done"])):
        instance.wait_for_bootstrap()


def test_wait_for_bootstrap_disabled(instance):
    """wait_for_bootstrap() returns when cloud-init is disabled - nothing will provision the instance."""
    with mock.patch.object(EC2Instance, "execute_command", side_effect=_fake_execute_command(["disabled"])):
        instance.wait_for_bootstrap()


# -- wait_for_bootstrap: failures ---------------------------------------------


def test_wait_for_bootstrap_error(instance):
    """wait_for_bootstrap() raises with diagnostics when cloud-init reports an error."""
    with mock.patch.object(EC2Instance, "execute_command", side_effect=_fake_execute_command(["error"])):
        with pytest.raises(IHBootstrapFailed) as exc_info:
            instance.wait_for_bootstrap()

    message = str(exc_info.value)
    assert "i-1234567890abcdef" in message
    assert "ih-bootstrap exited 1" in message
    assert "Could not apply the manifest" in message


def test_wait_for_bootstrap_timeout(instance):
    """wait_for_bootstrap() raises with diagnostics when cloud-init is still running at the deadline."""
    with mock.patch.object(EC2Instance, "execute_command", side_effect=_fake_execute_command(["running"])):
        with pytest.raises(IHBootstrapTimeout) as exc_info:
            instance.wait_for_bootstrap(timeout_seconds=0)

    message = str(exc_info.value)
    assert "still 'running' after 0 seconds" in message
    assert "Could not apply the manifest" in message


def test_wait_for_bootstrap_diagnostics_are_best_effort(instance):
    """Diagnostics that fail must not replace the failure they explain."""

    def _execute_command(command, **_):
        if command == "cloud-init status":
            return 0, "status: error\n", ""
        raise RuntimeError("Instance i-1234567890abcdef is terminated - SSM will never connect")

    with mock.patch.object(EC2Instance, "execute_command", side_effect=_execute_command):
        with pytest.raises(IHBootstrapFailed) as exc_info:
            instance.wait_for_bootstrap()

    message = str(exc_info.value)
    assert "finished as 'error'" in message
    assert "<unavailable: Instance i-1234567890abcdef is terminated" in message


def test_wait_for_bootstrap_diagnostics_survive_client_error(instance):
    """An AWS-side failure while collecting diagnostics is reported, not raised."""

    def _execute_command(command, **_):
        if command == "cloud-init status":
            return 0, "status: error\n", ""
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no ssm:SendCommand"}}, "SendCommand")

    with mock.patch.object(EC2Instance, "execute_command", side_effect=_execute_command):
        with pytest.raises(IHBootstrapFailed) as exc_info:
            instance.wait_for_bootstrap()

    assert "<unavailable: An error occurred (AccessDeniedException)" in str(exc_info.value)


def test_wait_for_bootstrap_unknown_status_propagates(instance):
    """An unreadable cloud-init status is not silently treated as 'still running'."""
    with mock.patch.object(EC2Instance, "execute_command", return_value=(127, "", "command not found")):
        with pytest.raises(IHBootstrapUnknown):
            instance.wait_for_bootstrap()
