"""Tests for CloudFrontDistribution.exists, enable/disable, and delete()."""

from contextlib import contextmanager
from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.cloudfront_distribution import CloudFrontDistribution

DIST_ID = "E1A2B3C4D5E6F7"

# Patch target for the ``timeout`` context manager used inside the module.
_TIMEOUT_PATCH = "infrahouse_core.aws.cloudfront_distribution.timeout"
_SLEEP_PATCH = "infrahouse_core.aws.cloudfront_distribution.time.sleep"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def _config_response(enabled, etag="ETAG1"):
    """Return a mock get_distribution_config response."""
    return {
        "DistributionConfig": {"Enabled": enabled, "CallerReference": "ref-1"},
        "ETag": etag,
    }


@contextmanager
def _noop_timeout(_seconds):
    """A no-op replacement for ``infrahouse_core.timeout.timeout``."""
    yield


# -- properties ---------------------------------------------------------------


def test_distribution_id():
    """distribution_id returns the ID passed to the constructor."""
    dist = CloudFrontDistribution(DIST_ID)
    assert dist.distribution_id == DIST_ID


# -- exists -------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the distribution is found."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution.return_value = {
        "Distribution": {"Id": DIST_ID, "Status": "Deployed"}
    }

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert dist.exists is True
        mock_client.get_distribution.assert_called_once_with(Id=DIST_ID)


def test_exists_not_found():
    """exists returns False when NoSuchDistribution is raised."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution.side_effect = _make_client_error("NoSuchDistribution")

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        assert dist.exists is False


def test_exists_unexpected_error():
    """Unexpected errors are re-raised."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            _ = dist.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- enable / disable --------------------------------------------------------


def test_enable_already_enabled():
    """enable() is a no-op when the distribution is already enabled."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution_config.return_value = _config_response(enabled=True)

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        dist.enable()

    mock_client.update_distribution.assert_not_called()


def test_enable_disabled_distribution():
    """enable() enables a disabled distribution."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution_config.return_value = _config_response(enabled=False)
    mock_client.update_distribution.return_value = {"ETag": "ETAG2"}

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        dist.enable()

    mock_client.update_distribution.assert_called_once()
    call_kwargs = mock_client.update_distribution.call_args[1]
    assert call_kwargs["DistributionConfig"]["Enabled"] is True
    assert call_kwargs["IfMatch"] == "ETAG1"


def test_disable_already_disabled():
    """disable() is a no-op when the distribution is already disabled."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution_config.return_value = _config_response(enabled=False)

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        dist.disable()

    mock_client.update_distribution.assert_not_called()


def test_disable_enabled_distribution():
    """disable() disables an enabled distribution."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution_config.return_value = _config_response(enabled=True)
    mock_client.update_distribution.return_value = {"ETag": "ETAG2"}

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        dist.disable()

    mock_client.update_distribution.assert_called_once()
    call_kwargs = mock_client.update_distribution.call_args[1]
    assert call_kwargs["DistributionConfig"]["Enabled"] is False
    assert call_kwargs["IfMatch"] == "ETAG1"


# -- delete -------------------------------------------------------------------


def test_delete_already_disabled():
    """delete() skips the disable step if the distribution is already disabled."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()

    # get_distribution_config – called by disable() then by delete() for ETag
    mock_client.get_distribution_config.side_effect = [
        _config_response(enabled=False, etag="ETAG1"),
        _config_response(enabled=False, etag="ETAG1"),
    ]
    # get_distribution – Deployed status
    mock_client.get_distribution.return_value = {
        "Distribution": {"Id": DIST_ID, "Status": "Deployed"}
    }

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ), mock.patch(_TIMEOUT_PATCH, _noop_timeout):
        dist.delete()

    mock_client.update_distribution.assert_not_called()
    mock_client.delete_distribution.assert_called_once_with(Id=DIST_ID, IfMatch="ETAG1")


def test_delete_enabled_distribution():
    """delete() disables, waits, then deletes an enabled distribution."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()

    # get_distribution_config – first call (disable), second call (re-fetch ETag)
    mock_client.get_distribution_config.side_effect = [
        _config_response(enabled=True, etag="ETAG1"),
        _config_response(enabled=False, etag="ETAG3"),
    ]
    # update_distribution returns new ETag
    mock_client.update_distribution.return_value = {"ETag": "ETAG2"}
    # get_distribution – Deployed (for _wait_until_deployed)
    mock_client.get_distribution.return_value = {
        "Distribution": {"Id": DIST_ID, "Status": "Deployed"}
    }

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ), mock.patch(_TIMEOUT_PATCH, _noop_timeout):
        dist.delete()

    # Should have disabled the distribution
    mock_client.update_distribution.assert_called_once()
    call_kwargs = mock_client.update_distribution.call_args[1]
    assert call_kwargs["DistributionConfig"]["Enabled"] is False
    assert call_kwargs["IfMatch"] == "ETAG1"

    # Should delete with the re-fetched ETag
    mock_client.delete_distribution.assert_called_once_with(Id=DIST_ID, IfMatch="ETAG3")


def test_delete_not_found():
    """delete() on a non-existent distribution is a no-op."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution_config.side_effect = _make_client_error("NoSuchDistribution")

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        dist.delete()  # Should not raise

    mock_client.delete_distribution.assert_not_called()


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution_config.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ):
        with pytest.raises(ClientError) as exc_info:
            dist.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- _wait_until_deployed -----------------------------------------------------


def test_wait_until_deployed_immediate():
    """_wait_until_deployed returns immediately if status is Deployed."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution.return_value = {
        "Distribution": {"Id": DIST_ID, "Status": "Deployed"}
    }

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ), mock.patch(_TIMEOUT_PATCH, _noop_timeout):
        dist._wait_until_deployed()  # pylint: disable=protected-access

    mock_client.get_distribution.assert_called_once_with(Id=DIST_ID)


def test_wait_until_deployed_polls():
    """_wait_until_deployed polls until status is Deployed."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution.side_effect = [
        {"Distribution": {"Id": DIST_ID, "Status": "InProgress"}},
        {"Distribution": {"Id": DIST_ID, "Status": "InProgress"}},
        {"Distribution": {"Id": DIST_ID, "Status": "Deployed"}},
    ]

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ), mock.patch(_TIMEOUT_PATCH, _noop_timeout), mock.patch(_SLEEP_PATCH):
        dist._wait_until_deployed()  # pylint: disable=protected-access

    assert mock_client.get_distribution.call_count == 3


def test_wait_until_deployed_timeout():
    """_wait_until_deployed raises TimeoutError when the timeout() context manager fires."""
    dist = CloudFrontDistribution(DIST_ID, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_distribution.return_value = {
        "Distribution": {"Id": DIST_ID, "Status": "InProgress"}
    }

    def sleep_raises(_seconds):
        raise TimeoutError("Executing timed out after 1800 seconds")

    with mock.patch.object(
        CloudFrontDistribution, "_client", new_callable=mock.PropertyMock, return_value=mock_client
    ), mock.patch(_TIMEOUT_PATCH, _noop_timeout), mock.patch(_SLEEP_PATCH, side_effect=sleep_raises):
        with pytest.raises(TimeoutError, match="timed out"):
            dist._wait_until_deployed()  # pylint: disable=protected-access
