"""
What botocore does with the token file, which get_aws_session relies on to decide when to log in again.

If a botocore upgrade changes any of this, these tests say so.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from os import path as osp

import boto3
import botocore.session
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import (
    SSOError,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)
from botocore.tokens import SSOTokenProvider

from .conftest import PROFILE_B, SSO_REGION, SSO_SESSION, START_URL


def write_token_file(cache_dir: str, content: str) -> None:
    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    with open(
        osp.join(cache_dir, hashlib.sha1(SSO_SESSION.encode("utf-8")).hexdigest() + ".json"), "w", encoding="utf-8"
    ) as token_file:
        token_file.write(content)


def token(expires_at: datetime) -> str:
    return json.dumps(
        {
            "startUrl": START_URL,
            "region": SSO_REGION,
            "accessToken": "some-access-token",
            "expiresAt": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )


def load_token():
    return SSOTokenProvider(botocore.session.Session(profile=PROFILE_B)).load_token().get_frozen_token()


def test_missing_token_file(aws_config):
    with pytest.raises(SSOTokenLoadError):
        load_token()


def test_expired_token_without_refresh(aws_config, token_cache_dir):
    write_token_file(token_cache_dir, token(datetime.now(timezone.utc) - timedelta(hours=1)))

    with pytest.raises(TokenRetrievalError, match="Token has expired and refresh failed"):
        load_token()


def test_revoked_token(aws_config, token_cache_dir):
    """A token that hasn't reached expiresAt but that AWS rejects, e.g. after the SSO session ended."""
    write_token_file(token_cache_dir, token(datetime.now(timezone.utc) + timedelta(hours=4)))
    session = boto3.Session(profile_name=PROFILE_B)

    def unauthorized(**kwargs):  # pylint: disable=unused-argument
        return AWSResponse(None, 401, {}, None), {
            "Error": {"Code": "UnauthorizedException", "Message": "Session token not found or invalid"},
            "ResponseMetadata": {"HTTPStatusCode": 401},
        }

    session.events.register("before-call.sso.GetRoleCredentials", unauthorized)
    with pytest.raises(UnauthorizedSSOTokenError) as exc_info:
        session.get_credentials().get_frozen_credentials()
    assert isinstance(exc_info.value, SSOError)


@pytest.mark.parametrize("content, error", [("{not json", KeyError), ("", KeyError), ("null", TypeError)])
def test_corrupt_token_file_is_not_an_sso_error(aws_config, token_cache_dir, content, error):
    """
    A corrupt token file raises KeyError or TypeError, not SSOError, so get_aws_session doesn't log in again over it.
    """
    write_token_file(token_cache_dir, content)

    with pytest.raises(error) as exc_info:
        load_token()
    assert not isinstance(exc_info.value, (SSOError, TokenRetrievalError))
