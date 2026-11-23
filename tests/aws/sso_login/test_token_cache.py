"""
aws_sso_login saves its token to the AWS CLI's shared token cache, where botocore finds it for every profile of the
sso-session.
"""

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from os import path as osp

import boto3
import botocore.session
import dateutil.parser
import pytest
from botocore.awsrequest import AWSResponse
from botocore.tokens import SSOTokenProvider, _sso_json_dumps
from botocore.utils import JSONFileCache, SSOTokenLoader

from infrahouse_core.aws import aws_sso_login
from infrahouse_core.aws.config import AWSConfig
from infrahouse_core.aws.sso_login import _dump_sso_token

from .conftest import (
    ACCESS_TOKEN,
    ACCOUNT_B,
    CLIENT_ID,
    CLIENT_SECRET,
    CLIENT_SECRET_EXPIRES_AT,
    PROFILE_A,
    PROFILE_B,
    REFRESH_TOKEN,
    SSO_REGION,
    SSO_SESSION,
    START_URL,
    TOKEN_EXPIRES_IN,
    config_text,
    write_config,
)

UTC_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def token_path(cache_dir: str) -> str:
    """botocore names the file after the SHA-1 of the sso-session name."""
    return osp.join(cache_dir, hashlib.sha1(SSO_SESSION.encode("utf-8")).hexdigest() + ".json")


def mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_token_file_where_botocore_looks(aws_config, oidc, browser, token_cache_dir):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    # The same path botocore's own loader computes for this sso-session.
    cache = JSONFileCache(SSOTokenProvider._SSO_TOKEN_CACHE_DIR)  # pylint: disable=protected-access
    # pylint: disable-next=protected-access
    assert cache._convert_cache_key(SSOTokenLoader()._generate_cache_key(START_URL, SSO_SESSION)) == token_path(
        token_cache_dir
    )
    assert os.listdir(token_cache_dir) == [osp.basename(token_path(token_cache_dir))]
    assert mode(token_path(token_cache_dir)) == 0o600
    assert mode(token_cache_dir) == 0o700


def test_token_file_content(aws_config, oidc, browser, token_cache_dir):
    oidc.expect_pkce_login()
    before = datetime.now(timezone.utc).replace(microsecond=0)

    aws_sso_login(aws_config, PROFILE_A)

    after = datetime.now(timezone.utc)
    with open(token_path(token_cache_dir), encoding="utf-8") as token_file:
        token = json.load(token_file)
    assert set(token) == {
        "startUrl",
        "region",
        "accessToken",
        "expiresAt",
        "clientId",
        "clientSecret",
        "registrationExpiresAt",
        "refreshToken",
    }
    assert token["startUrl"] == START_URL
    assert token["region"] == SSO_REGION
    assert token["accessToken"] == ACCESS_TOKEN
    assert token["refreshToken"] == REFRESH_TOKEN
    assert token["clientId"] == CLIENT_ID
    assert token["clientSecret"] == CLIENT_SECRET
    expires_at = dateutil.parser.parse(token["expiresAt"])
    assert before + timedelta(seconds=TOKEN_EXPIRES_IN) <= expires_at <= after + timedelta(seconds=TOKEN_EXPIRES_IN)


def test_no_refresh_token_when_create_token_returns_none(aws_config, oidc, browser, token_cache_dir):
    oidc.expect_pkce_login(refresh_token=False)

    aws_sso_login(aws_config, PROFILE_A)

    with open(token_path(token_cache_dir), encoding="utf-8") as token_file:
        assert "refreshToken" not in json.load(token_file)


def test_dates_as_botocore_writes_them(aws_config, oidc, browser, token_cache_dir):
    """expiresAt and registrationExpiresAt are UTC ISO 8601, and the file is what botocore's _sso_json_dumps makes."""
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    with open(token_path(token_cache_dir), encoding="utf-8") as token_file:
        content = token_file.read()
    token = json.loads(content)
    for field in ("expiresAt", "registrationExpiresAt"):
        assert UTC_FORMAT.match(token[field]), token[field]
        # botocore parses both with dateutil (SSOTokenProvider._refresher and _refresh_access_token).
        assert dateutil.parser.parse(token[field]).utcoffset() == timedelta(0)
    # The AWS CLI converts clientSecretExpiresAt with datetime.fromtimestamp(..., tzutc()).
    assert dateutil.parser.parse(token["registrationExpiresAt"]) == datetime.fromtimestamp(
        CLIENT_SECRET_EXPIRES_AT, timezone.utc
    )
    as_datetimes = dict(
        token,
        expiresAt=dateutil.parser.parse(token["expiresAt"]),
        registrationExpiresAt=dateutil.parser.parse(token["registrationExpiresAt"]),
    )
    assert content == _sso_json_dumps(as_datetimes)


def test_dump_matches_botocore():
    token = {
        "startUrl": START_URL,
        "region": SSO_REGION,
        "accessToken": ACCESS_TOKEN,
        "expiresAt": datetime(2026, 11, 23, 4, 5, 6, 789000, tzinfo=timezone.utc),
        "clientId": CLIENT_ID,
        "clientSecret": CLIENT_SECRET,
        "registrationExpiresAt": datetime.fromtimestamp(CLIENT_SECRET_EXPIRES_AT, timezone.utc),
        "refreshToken": REFRESH_TOKEN,
    }
    assert _dump_sso_token(token) == _sso_json_dumps(token)
    assert json.loads(_dump_sso_token(token))["expiresAt"] == "2026-11-23T04:05:06Z"


def test_botocore_loads_token_for_another_profile(aws_config, oidc, browser):
    """After a login for profile A, botocore's own classes find the token for profile B with no login running."""
    oidc.expect_pkce_login()
    aws_sso_login(aws_config, PROFILE_A)
    calls_after_login = list(oidc.calls)

    loaded = SSOTokenLoader(JSONFileCache(SSOTokenProvider._SSO_TOKEN_CACHE_DIR))(  # pylint: disable=protected-access
        START_URL, session_name=SSO_SESSION
    )
    assert loaded["accessToken"] == ACCESS_TOKEN

    provider = SSOTokenProvider(botocore.session.Session(profile=PROFILE_B))
    assert provider.load_token().get_frozen_token().token == ACCESS_TOKEN

    assert oidc.calls == calls_after_login
    oidc.stubber.assert_no_pending_responses()


def test_profile_b_gets_role_credentials_from_shared_token(aws_config, oidc, browser):
    """A plain boto3 Session for profile B exchanges the saved token for its own role credentials."""
    oidc.expect_pkce_login()
    aws_sso_login(aws_config, PROFILE_A)

    session = boto3.Session(profile_name=PROFILE_B)
    seen = []

    def get_role_credentials(params, **kwargs):  # pylint: disable=unused-argument
        seen.append(params)
        return AWSResponse(None, 200, {}, None), {
            "roleCredentials": {
                "accessKeyId": "ASIASTUBPROFILEB",
                "secretAccessKey": "stub-role-secret",
                "sessionToken": "stub-role-session-token",
                "expiration": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000),
            }
        }

    session.events.register("before-call.sso.GetRoleCredentials", get_role_credentials)
    credentials = session.get_credentials().get_frozen_credentials()

    assert credentials.access_key == "ASIASTUBPROFILEB"
    assert len(seen) == 1
    assert seen[0]["headers"]["x-amz-sso_bearer_token"] == ACCESS_TOKEN
    assert seen[0]["query_string"] == {"role_name": "ReadOnlyAccess", "account_id": ACCOUNT_B}
    assert [name for name, _ in oidc.calls].count("RegisterClient") == 1


def test_returned_session_uses_the_profile(aws_config, oidc, browser):
    """aws_sso_login returns a profile session that botocore authenticates; ih-aws holds no role credentials."""
    oidc.expect_pkce_login()

    session = aws_sso_login(aws_config, PROFILE_A)

    assert session.profile_name == PROFILE_A
    assert session.region_name == "us-east-2"
    assert session.get_credentials().method == "sso"


def test_returned_session_region_argument(aws_config, oidc, browser):
    oidc.expect_pkce_login()

    assert aws_sso_login(aws_config, PROFILE_A, region="eu-west-1").region_name == "eu-west-1"


def test_overwrites_previous_token(aws_config, oidc, browser, token_cache_dir):
    os.makedirs(token_cache_dir, mode=0o700)
    with open(token_path(token_cache_dir), "w", encoding="utf-8") as token_file:
        json.dump({"startUrl": START_URL, "accessToken": "old-token", "expiresAt": "2020-01-01T00:00:00Z"}, token_file)
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    with open(token_path(token_cache_dir), encoding="utf-8") as token_file:
        assert json.load(token_file)["accessToken"] == ACCESS_TOKEN
    assert os.listdir(token_cache_dir) == [osp.basename(token_path(token_cache_dir))]


# --- The cache directory ---


@pytest.mark.parametrize("umask", [0o022, 0o077, 0o000])
def test_missing_directories_are_created_0700(aws_config, oidc, browser, home, token_cache_dir, umask):
    """~/.aws exists (it holds the config); ~/.aws/sso and ~/.aws/sso/cache are created with mode 0700."""
    os.chmod(osp.join(home, ".aws"), 0o755)
    oidc.expect_pkce_login()
    old_umask = os.umask(umask)
    try:
        aws_sso_login(aws_config, PROFILE_A)
    finally:
        os.umask(old_umask)

    assert mode(osp.join(home, ".aws")) == 0o755
    assert mode(osp.join(home, ".aws", "sso")) == 0o700
    assert mode(token_cache_dir) == 0o700
    assert mode(token_path(token_cache_dir)) == 0o600


def test_umask_without_owner_write_still_gives_0700(aws_config, oidc, browser, home, token_cache_dir):
    """mkdir applies the umask; the directories ih-aws creates still end up 0700."""
    oidc.expect_pkce_login()
    old_umask = os.umask(0o277)
    try:
        aws_sso_login(aws_config, PROFILE_A)
    finally:
        os.umask(old_umask)

    assert mode(osp.join(home, ".aws", "sso")) == 0o700
    assert mode(token_cache_dir) == 0o700


def test_no_aws_directory_at_all(home, oidc, browser, token_cache_dir, tmp_path, monkeypatch):
    """With no ~/.aws, every missing level is created with mode 0700."""
    config_dir = tmp_path / "elsewhere"
    config_dir.mkdir()
    (config_dir / "config").write_text(config_text())
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config_dir / "config"))
    oidc.expect_pkce_login()

    aws_sso_login(AWSConfig(aws_home=str(config_dir)), PROFILE_A)

    assert mode(osp.join(home, ".aws")) == 0o700
    assert mode(osp.join(home, ".aws", "sso")) == 0o700
    assert mode(token_cache_dir) == 0o700
    assert mode(token_path(token_cache_dir)) == 0o600


@pytest.mark.parametrize("existing_mode", [0o755, 0o750, 0o700])
def test_existing_cache_directory_mode_is_left_alone(aws_config, oidc, browser, home, token_cache_dir, existing_mode):
    os.makedirs(token_cache_dir)
    os.chmod(osp.join(home, ".aws", "sso"), existing_mode)
    os.chmod(token_cache_dir, existing_mode)
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert mode(osp.join(home, ".aws", "sso")) == existing_mode
    assert mode(token_cache_dir) == existing_mode
    assert mode(token_path(token_cache_dir)) == 0o600


def test_aws_cli_files_in_cache_are_untouched(aws_config, oidc, browser, token_cache_dir):
    """ih-aws never reads or writes the AWS CLI's other files in ~/.aws/sso/cache, e.g. its registrations."""
    os.makedirs(token_cache_dir, mode=0o700)
    other = osp.join(token_cache_dir, "botocore-client-id-us-west-1.json")
    with open(other, "w", encoding="utf-8") as other_file:
        other_file.write('{"clientId": "cli-client", "clientSecret": "cli-secret"}')
    os.chmod(other, 0o600)
    before = os.stat(other)
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    after = os.stat(other)
    with open(other, encoding="utf-8") as other_file:
        assert other_file.read() == '{"clientId": "cli-client", "clientSecret": "cli-secret"}'
    assert (after.st_mtime_ns, after.st_mode) == (before.st_mtime_ns, before.st_mode)
    assert sorted(os.listdir(token_cache_dir)) == sorted(
        [osp.basename(other), osp.basename(token_path(token_cache_dir))]
    )


def test_unwritable_cache_fails_before_login(aws_config, oidc, browser, home):
    """If ~/.aws/sso can't be created, aws_sso_login fails before it asks the user to approve anything."""
    with open(osp.join(home, ".aws", "sso"), "w", encoding="utf-8") as blocker:
        blocker.write("not a directory")

    with pytest.raises(OSError):
        aws_sso_login(aws_config, PROFILE_A)

    assert not oidc.calls
    assert not browser.urls


# --- ~/.infrahouse-toolkit ---


def snapshot(directory: str) -> dict:
    result = {}
    for root, dirs, files in os.walk(directory):
        for name in dirs + files:
            full = osp.join(root, name)
            info = os.stat(full)
            content = None
            if osp.isfile(full):
                with open(full, "rb") as handle:
                    content = handle.read()
            result[osp.relpath(full, directory)] = (info.st_mode, info.st_mtime_ns, content)
    result["."] = os.stat(directory).st_mode
    return result


def test_nothing_written_to_infrahouse_toolkit(aws_config, oidc, browser, home):
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert not osp.exists(osp.join(home, ".infrahouse-toolkit"))


def test_existing_infrahouse_toolkit_files_unchanged(aws_config, oidc, browser, home):
    toolkit = osp.join(home, ".infrahouse-toolkit")
    os.mkdir(toolkit, 0o700)
    role_credentials = osp.join(toolkit, "sso-role-credentials-" + "0" * 64 + ".json")
    with open(role_credentials, "w", encoding="utf-8") as cache_file:
        json.dump({"version": 1, "key": PROFILE_A, "expires_at": 4102444800.0, "data": {}}, cache_file)
    with open(osp.join(toolkit, "cache.db"), "wb") as cache_db:
        cache_db.write(b"SQLite format 3\x00")
    os.mkdir(osp.join(toolkit, "00"))
    before = snapshot(toolkit)
    oidc.expect_pkce_login()

    aws_sso_login(aws_config, PROFILE_A)

    assert snapshot(toolkit) == before


def test_custom_scopes_saved_token_still_loads(home, oidc, browser):
    """Scopes from sso_registration_scopes don't change where the token goes."""
    write_config(home, scopes="sso:account:access,codewhisperer:completions")
    oidc.expect_pkce_login(scopes=["sso:account:access", "codewhisperer:completions"])

    aws_sso_login(AWSConfig(), PROFILE_A)

    provider = SSOTokenProvider(botocore.session.Session(profile=PROFILE_B))
    assert provider.load_token().get_frozen_token().token == ACCESS_TOKEN
