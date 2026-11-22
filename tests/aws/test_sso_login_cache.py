"""Tests for how aws_sso_login() caches each profile's SSO role credentials."""

import json
import os
import pickle
import re
import stat
import time
from unittest import mock

import pytest

from infrahouse_core.aws import aws_sso_login
from infrahouse_core.aws.config import AWSConfig

# Spelled out rather than imported: renaming the namespace renames every user's cache file
# and costs each of them another SSO approval per profile, so a rename should break this test.
CACHE_FILE_NAME = re.compile(r"^sso-role-credentials-[0-9a-f]{64}\.json$")


def _role_credentials(name: str, expires_in: int = 3600) -> dict:
    """What sso.get_role_credentials() returns under "roleCredentials"."""
    return {
        "accessKeyId": f"AKIA-{name}",
        "secretAccessKey": f"secret-{name}",
        "sessionToken": f"token-{name}",
        "expiration": int((time.time() + expires_in) * 1000),
    }


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home directory, so the cache lands in tmp_path."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    return home_dir


@pytest.fixture
def cache_dir(home):
    """Where aws_sso_login() keeps its cache."""
    return home / ".infrahouse-toolkit"


@pytest.fixture
def aws_config():
    """AWS config stand-in; region is always passed explicitly, so nothing is read from it."""
    return mock.MagicMock(spec=AWSConfig)


@pytest.fixture
def sso_flow():
    """The SSO device flow, replaced so no browser opens and no AWS call is made."""
    with mock.patch("infrahouse_core.aws._get_credentials") as flow:
        flow.return_value = _role_credentials("fresh")
        yield flow


def _login(aws_config, profile: str = "dev"):
    return aws_sso_login(aws_config, profile, region="us-west-2")


def _access_key(session) -> str:
    return session.get_credentials().access_key


def _cache_files(cache_dir) -> list:
    return sorted(name for name in os.listdir(cache_dir) if CACHE_FILE_NAME.match(name))


def _only_cache_file(cache_dir) -> str:
    files = _cache_files(cache_dir)
    assert len(files) == 1, files
    return str(cache_dir / files[0])


def _read_json(path) -> dict:
    with open(path, encoding="utf-8") as cache_file:
        return json.load(cache_file)


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_cache_hit_skips_the_sso_flow(home, aws_config, sso_flow):
    """The second login for a profile reuses the cached credentials instead of asking for approval again."""
    first = _login(aws_config)
    sso_flow.return_value = _role_credentials("second")
    second = _login(aws_config)

    sso_flow.assert_called_once_with(aws_config, "dev")
    assert _access_key(first) == _access_key(second) == "AKIA-fresh"


def test_cache_hit_returns_a_session_with_all_three_credentials(home, aws_config, sso_flow):
    """A session built from the cache carries the key id, the secret and the session token."""
    _login(aws_config)
    credentials = _login(aws_config).get_credentials()

    assert sso_flow.call_count == 1
    assert (credentials.access_key, credentials.secret_key, credentials.token) == (
        "AKIA-fresh",
        "secret-fresh",
        "token-fresh",
    )


def test_miss_runs_the_sso_flow_and_writes_the_file(home, cache_dir, aws_config, sso_flow):
    """With no cache file, the SSO flow runs and its result is written as plain JSON with its expiry."""
    session = _login(aws_config)

    sso_flow.assert_called_once_with(aws_config, "dev")
    assert _access_key(session) == "AKIA-fresh"
    record = _read_json(_only_cache_file(cache_dir))
    assert record["key"] == "dev"
    assert record["data"] == sso_flow.return_value
    assert record["expires_at"] == sso_flow.return_value["expiration"] / 1000


def _write_record(cache_dir, profile: str = "dev", **overrides) -> None:
    """Write a valid-looking cache file for a profile, then let the test break it."""
    _login_once_with(cache_dir, profile)
    path = _only_cache_file(cache_dir)
    record = _read_json(path)
    record.update(overrides)
    with open(path, "w", encoding="utf-8") as cache_file:
        json.dump(record, cache_file)


def _login_once_with(cache_dir, profile: str) -> None:
    """Populate the cache through aws_sso_login() itself, with credentials named "stale"."""
    with mock.patch("infrahouse_core.aws._get_credentials", return_value=_role_credentials("stale")):
        aws_sso_login(mock.MagicMock(spec=AWSConfig), profile, region="us-west-2")
    assert cache_dir.is_dir()


def _overwrite(cache_dir, content: bytes) -> None:
    """Replace the only cache file's bytes, keeping its name."""
    path = _only_cache_file(cache_dir)
    with open(path, "wb") as cache_file:
        cache_file.write(content)
    os.chmod(path, 0o644)


def _expired(cache_dir):
    _write_record(cache_dir, expires_at=time.time() - 60)


def _near_expiry(cache_dir):
    # Four minutes left: inside the five-minute margin.
    _write_record(cache_dir, expires_at=time.time() + 240)


def _not_json(cache_dir):
    _login_once_with(cache_dir, "dev")
    _overwrite(cache_dir, b"{not json")


def _truncated(cache_dir):
    _login_once_with(cache_dir, "dev")
    with open(_only_cache_file(cache_dir), "rb") as cache_file:
        content = cache_file.read()
    _overwrite(cache_dir, content[: len(content) // 2])


def _empty(cache_dir):
    _login_once_with(cache_dir, "dev")
    _overwrite(cache_dir, b"")


def _not_utf8(cache_dir):
    _login_once_with(cache_dir, "dev")
    _overwrite(cache_dir, b"\xff\xfe\x00\x01garbage")


def _wrong_shape(cache_dir):
    _login_once_with(cache_dir, "dev")
    _overwrite(cache_dir, b'["AKIA-stale", "secret-stale", "token-stale"]')


def _missing_secret(cache_dir):
    _login_once_with(cache_dir, "dev")
    record = _read_json(_only_cache_file(cache_dir))
    del record["data"]["secretAccessKey"]
    _overwrite(cache_dir, json.dumps(record).encode())


def _other_profile(cache_dir):
    # A file copied over from another profile's name: the key inside doesn't match.
    _write_record(cache_dir, key="prod")


def _expiry_too_big_for_a_float(cache_dir):
    # Valid JSON, but float() of a 401-digit int overflows.
    _write_record(cache_dir, expires_at=10**400)


def _deeply_nested(cache_dir):
    # Deeper than the recursion limit, so the JSON parser raises RecursionError.
    _login_once_with(cache_dir, "dev")
    _overwrite(cache_dir, b"[" * 200_000)


STALE_CACHES = {
    "expired": _expired,
    "near-expiry": _near_expiry,
    "not-json": _not_json,
    "truncated": _truncated,
    "empty": _empty,
    "not-utf8": _not_utf8,
    "wrong-shape": _wrong_shape,
    "missing-secret": _missing_secret,
    "other-profile": _other_profile,
    "expiry-too-big-for-a-float": _expiry_too_big_for_a_float,
    "deeply-nested": _deeply_nested,
}


@pytest.mark.parametrize("make_stale", STALE_CACHES.values(), ids=STALE_CACHES.keys())
def test_stale_or_corrupt_file_runs_the_sso_flow_and_rewrites_it(home, cache_dir, aws_config, sso_flow, make_stale):
    """Expired, nearly expired and corrupt files are misses: the SSO flow runs and the file is replaced."""
    make_stale(cache_dir)

    session = _login(aws_config)

    sso_flow.assert_called_once_with(aws_config, "dev")
    assert _access_key(session) == "AKIA-fresh"
    path = _only_cache_file(cache_dir)
    assert _read_json(path)["data"] == sso_flow.return_value
    assert _mode(path) == 0o600


def test_pickle_in_the_cache_file_is_never_unpickled(tmp_path, home, cache_dir, aws_config, sso_flow):
    """A pickle planted in the cache file is treated as garbage, not loaded (CVE-2025-69872)."""
    marker = tmp_path / "unpickled"

    class Payload:
        """Unpickling this creates the marker file."""

        def __reduce__(self):
            return open, (str(marker), "w")

    _login_once_with(cache_dir, "dev")
    _overwrite(cache_dir, pickle.dumps(Payload()))

    session = _login(aws_config)

    assert not marker.exists()
    sso_flow.assert_called_once_with(aws_config, "dev")
    assert _access_key(session) == "AKIA-fresh"


def test_cache_file_is_0600_in_a_0700_directory(home, cache_dir, aws_config, sso_flow):
    """The cache directory is private to the user and so is the file, even with a permissive umask."""
    old_umask = os.umask(0)
    try:
        _login(aws_config)
    finally:
        os.umask(old_umask)

    assert _mode(cache_dir) == 0o700
    assert _mode(_only_cache_file(cache_dir)) == 0o600


def test_existing_cache_directory_is_tightened_to_0700(home, cache_dir, aws_config, sso_flow):
    """A cache directory that was left group- and world-readable is set back to 0700."""
    cache_dir.mkdir()
    os.chmod(cache_dir, 0o755)

    _login(aws_config)

    assert _mode(cache_dir) == 0o700


@pytest.mark.parametrize(
    "profile",
    ["../escape", "../../../../../../../../tmp/escape", "/tmp/escape", "team/dev", "..", ".", "", "nul\x00byte"],
)
def test_profile_name_cannot_escape_the_cache_directory(tmp_path, home, cache_dir, aws_config, sso_flow, profile):
    """Path characters in a profile name never reach the filesystem: the only file written is a hashed name in the
    cache directory, and the next login for that profile finds it."""
    _login(aws_config, profile)
    _login(aws_config, profile)

    assert sso_flow.call_count == 1
    written = [os.path.join(root, name) for root, _, names in os.walk(tmp_path) for name in names]
    assert written == [_only_cache_file(cache_dir)]


def test_two_profiles_do_not_share_a_file(home, cache_dir, aws_config, sso_flow):
    """Each profile gets its own file and its own credentials back."""
    sso_flow.side_effect = [_role_credentials("dev"), _role_credentials("prod")]

    assert _access_key(_login(aws_config, "dev")) == "AKIA-dev"
    assert _access_key(_login(aws_config, "prod")) == "AKIA-prod"
    assert _access_key(_login(aws_config, "dev")) == "AKIA-dev"
    assert _access_key(_login(aws_config, "prod")) == "AKIA-prod"

    assert sso_flow.call_count == 2
    files = _cache_files(cache_dir)
    assert len(files) == 2
    assert sorted(_read_json(cache_dir / name)["key"] for name in files) == ["dev", "prod"]


def test_old_cache_files_are_left_alone(home, cache_dir, aws_config, sso_flow):
    """Files from the previous cache format stay as they are: they aren't read, rewritten or deleted."""
    cache_dir.mkdir(mode=0o700)
    old_files = {
        "cache.db": b"SQLite format 3\x00old",
        "cache.db-wal": b"old wal",
        "cache.db-shm": b"old shm",
        os.path.join("1a", "2b", "0123456789abcdef.val"): b"old value",
    }
    for name, content in old_files.items():
        path = cache_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    _login(aws_config)

    sso_flow.assert_called_once_with(aws_config, "dev")
    for name, content in old_files.items():
        assert (cache_dir / name).read_bytes() == content
