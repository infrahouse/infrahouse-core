from configparser import NoOptionError, NoSectionError
from textwrap import dedent

import pytest

from infrahouse_core.aws import AWSConfig


def _config(scopes_line: str) -> str:
    return dedent(f"""
        [sso-session my_session]
        sso_start_url = https://foo.com/start#
        sso_region = us-west-1
        {scopes_line}

        [profile my_profile]
        sso_session = my_session
        sso_account_id = 12345678
        sso_role_name = admin

        [profile legacy_profile]
        sso_start_url = https://legacy.com/start#
        """)


@pytest.mark.parametrize(
    "scopes_line, scopes",
    [
        ("", []),
        ("sso_registration_scopes = sso:account:access", ["sso:account:access"]),
        (
            "sso_registration_scopes = sso:account:access,codewhisperer:completions",
            ["sso:account:access", "codewhisperer:completions"],
        ),
        # Split on commas and strip whitespace, as the AWS CLI's parse_sso_registration_scopes does.
        (
            "sso_registration_scopes =  sso:account:access , codewhisperer:completions ,",
            ["sso:account:access", "codewhisperer:completions"],
        ),
        ("sso_registration_scopes = ,, ,", []),
        ("sso_registration_scopes =", []),
    ],
)
def test_get_sso_registration_scopes(scopes_line, scopes, tmp_path):
    (tmp_path / "config").write_text(_config(scopes_line))
    assert AWSConfig(aws_home=str(tmp_path)).get_sso_registration_scopes("my_profile") == scopes


def test_get_sso_registration_scopes_without_sso_session(tmp_path):
    (tmp_path / "config").write_text(_config(""))
    with pytest.raises(NoOptionError):
        AWSConfig(aws_home=str(tmp_path)).get_sso_registration_scopes("legacy_profile")


def test_get_sso_registration_scopes_unknown_profile(tmp_path):
    (tmp_path / "config").write_text(_config(""))
    with pytest.raises(NoSectionError):
        AWSConfig(aws_home=str(tmp_path)).get_sso_registration_scopes("no_such_profile")


def test_get_sso_registration_scopes_missing_session_section(tmp_path):
    """The profile names an sso-session that has no section."""
    (tmp_path / "config").write_text(dedent("""
            [profile my_profile]
            sso_session = missing_session
            """))
    with pytest.raises(NoSectionError):
        AWSConfig(aws_home=str(tmp_path)).get_sso_registration_scopes("my_profile")
