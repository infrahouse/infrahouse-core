"""
get_aws_session against real botocore. Only the HTTP layer is faked (conftest.FakeAWS), so each error that sends
get_aws_session to aws_sso_login comes from botocore itself, on the path ih-aws takes: credential resolution while
botocore signs the STS GetCallerIdentity request.
"""

import hashlib
import json
import sys
from os import path as osp

import pytest
from botocore.exceptions import (
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
)

import infrahouse_core.aws
from infrahouse_core.aws import get_aws_session

from .conftest import (
    ACCESS_TOKEN,
    PROFILE_A,
    PROFILE_B,
    SSO_SESSION,
    FakeAWS,
    write_cli_token,
)


@pytest.fixture
def caught(monkeypatch) -> list:
    """The exception get_aws_session was handling each time it called aws_sso_login. The real login still runs."""
    errors = []
    real_login = infrahouse_core.aws.aws_sso_login

    def spy(*args, **kwargs):
        errors.append(sys.exc_info()[1])
        return real_login(*args, **kwargs)

    monkeypatch.setattr(infrahouse_core.aws, "aws_sso_login", spy)
    return errors


@pytest.mark.parametrize(
    "token_state, error_class, old_token_sent",
    [
        # No token file at all.
        ("missing", SSOTokenLoadError, False),
        # Expired, with no refresh fields: botocore can't refresh it.
        ("expired", TokenRetrievalError, False),
        # Not expired, but GetRoleCredentials answers 401: revoked, or the SSO session ended. This used to crash ih-aws.
        ("revoked", UnauthorizedSSOTokenError, True),
    ],
)
def test_logs_in_when_botocore_cannot_use_the_token(
    aws_config, oidc, browser, fake_aws, token_cache_dir, caught, token_state, error_class, old_token_sent
):
    if token_state == "expired":
        write_cli_token(token_cache_dir, "expired-access-token", expires_in=-3600)
    elif token_state == "revoked":
        write_cli_token(token_cache_dir, "revoked-access-token", expires_in=4 * 3600)
    oidc.expect_pkce_login()

    session = get_aws_session(aws_config, PROFILE_A, "us-east-2")

    # botocore raised it, through get_caller_identity(), and get_aws_session caught it.
    assert [type(error) for error in caught] == [error_class]
    # A login ran, and botocore then used its token for the profile's role credentials.
    assert oidc.operations == ["RegisterClient", "CreateToken"]
    expected_tokens = (["revoked-access-token"] if old_token_sent else []) + [ACCESS_TOKEN]
    assert fake_aws.role_credential_tokens == expected_tokens
    assert len(fake_aws.sts_authorizations) == 1
    assert f"Credential={FakeAWS.ROLE_ACCESS_KEY}/" in fake_aws.sts_authorizations[0]
    assert session.get_credentials().access_key == FakeAWS.ROLE_ACCESS_KEY
    token_path = osp.join(token_cache_dir, hashlib.sha1(SSO_SESSION.encode("utf-8")).hexdigest() + ".json")
    with open(token_path, encoding="utf-8") as token_file:
        assert json.load(token_file)["accessToken"] == ACCESS_TOKEN


def test_revoked_token_with_use_device_code(aws_config, oidc, browser, fake_aws, token_cache_dir, caught, no_sleep):
    write_cli_token(token_cache_dir, "revoked-access-token", expires_in=4 * 3600)
    oidc.expect_device_login()

    get_aws_session(aws_config, PROFILE_A, "us-east-2", use_device_code=True)

    assert [type(error) for error in caught] == [UnauthorizedSSOTokenError]
    assert oidc.operations == ["RegisterClient", "StartDeviceAuthorization", "CreateToken", "CreateToken"]
    assert fake_aws.role_credential_tokens == ["revoked-access-token", ACCESS_TOKEN]


def test_valid_token_needs_no_login(aws_config, oidc, browser, fake_aws, token_cache_dir, caught):
    """After a login for one profile, another profile of the session connects with no login: `ih-aws credentials`."""
    write_cli_token(token_cache_dir, ACCESS_TOKEN, expires_in=4 * 3600)

    for profile in (PROFILE_A, PROFILE_B):
        session = get_aws_session(aws_config, profile, "us-east-2")
        assert session.profile_name == profile
        assert session.get_credentials().access_key == FakeAWS.ROLE_ACCESS_KEY

    assert not caught
    assert not oidc.calls
    assert not browser.urls
    assert fake_aws.role_credential_tokens.count(ACCESS_TOKEN) >= 2
    assert len(fake_aws.sts_authorizations) == 2
