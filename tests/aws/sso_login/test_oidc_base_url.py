"""
The authorize endpoint isn't in the sso-oidc service model. Like the AWS CLI, ih-aws gets its base URL from botocore by
short-circuiting a RegisterClient request before it is sent.
"""

from unittest import mock

import boto3
import pytest
from botocore import UNSIGNED
from botocore.config import Config

from infrahouse_core.aws.sso_login import _get_oidc_base_url


@pytest.mark.parametrize(
    "region, fips, url",
    [
        ("us-west-1", False, "https://oidc.us-west-1.amazonaws.com"),
        ("eu-central-1", False, "https://oidc.eu-central-1.amazonaws.com"),
        ("us-east-1", True, "https://oidc-fips.us-east-1.amazonaws.com"),
        ("us-gov-west-1", False, "https://oidc.us-gov-west-1.amazonaws.com"),
        ("cn-north-1", False, "https://oidc.cn-north-1.amazonaws.com.cn"),
    ],
)
def test_base_url_from_botocore(home, region, fips, url):
    client = boto3.Session().client(
        "sso-oidc", region_name=region, config=Config(signature_version=UNSIGNED, use_fips_endpoint=fips)
    )
    # pylint: disable-next=protected-access
    with mock.patch.object(client._endpoint, "make_request", side_effect=AssertionError("sent a request")) as send:
        assert _get_oidc_base_url(client) == url
    send.assert_not_called()


def test_handler_removed_afterwards(home):
    """After the lookup, the client's requests are sent again, not short-circuited."""
    client = boto3.Session().client("sso-oidc", region_name="us-west-1", config=Config(signature_version=UNSIGNED))
    _get_oidc_base_url(client)

    # pylint: disable-next=protected-access
    with mock.patch.object(client._endpoint, "make_request", side_effect=AssertionError("sent a request")) as send:
        with pytest.raises(AssertionError, match="sent a request"):
            client.register_client(clientName="x", clientType="public")
    send.assert_called_once()
