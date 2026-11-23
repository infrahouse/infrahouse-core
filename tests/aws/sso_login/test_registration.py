"""
aws_sso_login registers a new client on every login. It never reuses a client from the token file.
"""

import hashlib
import json
import os
from os import path as osp

import pytest

from infrahouse_core.aws import aws_sso_login

from .conftest import (
    CLIENT_ID,
    CLIENT_SECRET,
    PROFILE_A,
    PROFILE_B,
    SSO_REGION,
    SSO_SESSION,
    START_URL,
)


def token_path(cache_dir: str) -> str:
    return osp.join(cache_dir, hashlib.sha1(SSO_SESSION.encode("utf-8")).hexdigest() + ".json")


@pytest.fixture
def token_with_valid_registration(token_cache_dir) -> str:
    """A token file from an earlier login: the token expired, the registration has months left."""
    os.makedirs(token_cache_dir, mode=0o700)
    path = token_path(token_cache_dir)
    with open(path, "w", encoding="utf-8") as token_file:
        json.dump(
            {
                "startUrl": START_URL,
                "region": SSO_REGION,
                "accessToken": "old-access-token",
                "expiresAt": "2020-01-01T00:00:00Z",
                "clientId": "old-client-id",
                "clientSecret": "old-client-secret",
                "registrationExpiresAt": "2099-01-01T00:00:00Z",
                "refreshToken": "old-refresh-token",
            },
            token_file,
        )
    return path


def test_pkce_registers_despite_valid_registration_in_token_file(
    aws_config, oidc, browser, token_with_valid_registration
):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert oidc.operations.count("RegisterClient") == 1
    assert oidc.calls_to("CreateToken")[0]["clientId"] == CLIENT_ID
    with open(token_with_valid_registration, encoding="utf-8") as token_file:
        token = json.load(token_file)
    assert (token["clientId"], token["clientSecret"]) == (CLIENT_ID, CLIENT_SECRET)


def test_device_flow_registers_despite_valid_registration_in_token_file(
    aws_config, oidc, browser, token_with_valid_registration, no_sleep
):
    oidc.expect_device_login()

    aws_sso_login(aws_config, PROFILE_A, use_device_code=True)

    assert oidc.operations.count("RegisterClient") == 1
    assert oidc.calls_to("StartDeviceAuthorization")[0]["clientId"] == CLIENT_ID


def test_every_login_registers(aws_config, oidc, local_browser, no_sleep):
    for profile in (PROFILE_A, PROFILE_B, PROFILE_A):
        local_browser()
        oidc.expect_pkce_login()
        aws_sso_login(aws_config, profile)
    oidc.expect_device_login()
    aws_sso_login(aws_config, PROFILE_B, use_device_code=True)

    assert oidc.operations.count("RegisterClient") == 4
    oidc.stubber.assert_no_pending_responses()
