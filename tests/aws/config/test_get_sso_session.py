from configparser import NoOptionError, NoSectionError
from textwrap import dedent

import pytest

from infrahouse_core.aws import AWSConfig

CONTENT = dedent("""
    [default]
    sso_session = default_session

    [sso-session foo_session]
    sso_start_url = https://foo.com/start#
    sso_region = us-west-1

    [profile foo_profile]
    sso_session = foo_session
    sso_account_id = 12345678
    sso_role_name = admin

    [profile legacy_profile]
    sso_start_url = https://legacy.com/start#
    sso_region = us-west-1
    """)


@pytest.mark.parametrize(
    "profile, session",
    [
        ("foo_profile", "foo_session"),
        ("default", "default_session"),
        (None, "default_session"),
    ],
)
def test_get_sso_session(profile, session, tmp_path):
    (tmp_path / "config").write_text(CONTENT)
    assert AWSConfig(aws_home=str(tmp_path)).get_sso_session(profile) == session


def test_get_sso_session_without_sso_session(tmp_path):
    """A legacy profile without sso_session raises NoOptionError."""
    (tmp_path / "config").write_text(CONTENT)
    with pytest.raises(NoOptionError):
        AWSConfig(aws_home=str(tmp_path)).get_sso_session("legacy_profile")


def test_get_sso_session_unknown_profile(tmp_path):
    (tmp_path / "config").write_text(CONTENT)
    with pytest.raises(NoSectionError):
        AWSConfig(aws_home=str(tmp_path)).get_sso_session("no_such_profile")
