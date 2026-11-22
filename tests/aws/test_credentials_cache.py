"""Tests for CredentialsCache: expiring JSON records in a private directory."""

import json
import logging
import os
import stat
import time
from unittest import mock

import pytest

from infrahouse_core.aws.credentials_cache import CredentialsCache

NAMESPACE = "test-credentials"


@pytest.fixture
def cache_dir(tmp_path):
    """Cache directory that doesn't exist yet."""
    return tmp_path / "cache"


@pytest.fixture
def cache(cache_dir):
    """A cache with the default expiry margin."""
    return CredentialsCache(NAMESPACE, directory=str(cache_dir))


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_save_then_load_returns_data(cache):
    """A saved record comes back from load() as the same dict."""
    data = {"accessKeyId": "AKIA", "secretAccessKey": "secret", "expiration": 1}
    cache.save("dev", data, expires_at=time.time() + 3600)

    assert cache.load("dev") == data


def test_saved_file_is_plain_json(cache):
    """The file holds a JSON object with the key, the expiry and the data, nothing else."""
    expires_at = time.time() + 3600
    cache.save("dev", {"token": "t"}, expires_at=expires_at)

    with open(cache.path("dev"), encoding="utf-8") as cache_file:
        record = json.load(cache_file)
    assert record == {"version": 1, "key": "dev", "expires_at": expires_at, "data": {"token": "t"}}


def test_load_missing_file_returns_none(cache):
    """No file is a cache miss."""
    assert cache.load("dev") is None


def test_load_creates_directory_with_0700(cache, cache_dir):
    """load() creates the cache directory, readable by the owner only, before it reads."""
    old_umask = os.umask(0)
    try:
        cache.load("dev")
    finally:
        os.umask(old_umask)

    assert _mode(cache_dir) == 0o700


def test_save_tightens_existing_directory_to_0700(cache, cache_dir):
    """An existing directory with looser permissions is set to 0700 before the write."""
    cache_dir.mkdir()
    os.chmod(cache_dir, 0o755)

    cache.save("dev", {"token": "t"}, expires_at=time.time() + 3600)

    assert _mode(cache_dir) == 0o700


def test_saved_file_is_0600(cache):
    """The cache file is readable and writable by the owner only, whatever the umask."""
    old_umask = os.umask(0)
    try:
        cache.save("dev", {"token": "t"}, expires_at=time.time() + 3600)
    finally:
        os.umask(old_umask)

    assert _mode(cache.path("dev")) == 0o600


def test_save_replaces_a_looser_file_with_a_0600_one(cache, cache_dir):
    """Saving over a 0644 file leaves a 0600 file: the old file is replaced, not rewritten in place."""
    cache_dir.mkdir(mode=0o700)
    path = cache.path("dev")
    with open(path, "w", encoding="utf-8") as stale:
        stale.write("{}")
    os.chmod(path, 0o644)

    cache.save("dev", {"token": "t"}, expires_at=time.time() + 3600)

    assert _mode(path) == 0o600


@pytest.mark.parametrize("margin, expected_hit", [(300, True), (900, False)])
def test_load_treats_records_inside_the_margin_as_expired(cache_dir, margin, expected_hit):
    """A record expiring in ten minutes is a hit with a five-minute margin and a miss with a fifteen-minute one."""
    cache = CredentialsCache(NAMESPACE, directory=str(cache_dir), expiry_margin=margin)
    cache.save("dev", {"token": "t"}, expires_at=time.time() + 600)

    assert (cache.load("dev") is not None) is expected_hit


def test_default_margin_is_five_minutes(cache):
    """With the default margin, four minutes left is a miss and six minutes left is a hit."""
    cache.save("four", {"token": "t"}, expires_at=time.time() + 240)
    cache.save("six", {"token": "t"}, expires_at=time.time() + 360)

    assert cache.load("four") is None
    assert cache.load("six") == {"token": "t"}


def _record(**overrides) -> dict:
    record = {"version": 1, "key": "dev", "expires_at": time.time() + 3600, "data": {"token": "t"}}
    record.update(overrides)
    return record


def _without(name: str) -> dict:
    record = _record()
    del record[name]
    return record


# Each case builds the bytes of a cache file that load() must treat as a miss.
BROKEN_FILES = {
    "empty": lambda: b"",
    "not-json": lambda: b"{not json",
    "truncated": lambda: json.dumps(_record()).encode()[:30],
    "not-utf8": lambda: b'{"version": 1, "key": "\xff\xfe"}',
    "json-list": lambda: b"[]",
    "json-string": lambda: b'"dev"',
    "json-null": lambda: b"null",
    "no-version": lambda: json.dumps(_without("version")).encode(),
    "newer-version": lambda: json.dumps(_record(version=2)).encode(),
    "other-key": lambda: json.dumps(_record(key="prod")).encode(),
    "no-expiry": lambda: json.dumps(_without("expires_at")).encode(),
    "expiry-string": lambda: json.dumps(_record(expires_at="tomorrow")).encode(),
    "expiry-bool": lambda: json.dumps(_record(expires_at=True)).encode(),
    "expiry-infinity": lambda: json.dumps(_record(expires_at=float("inf"))).encode(),
    "expiry-nan": lambda: json.dumps(_record(expires_at=float("nan"))).encode(),
    "expired": lambda: json.dumps(_record(expires_at=time.time() - 60)).encode(),
    "no-data": lambda: json.dumps(_without("data")).encode(),
    "data-not-object": lambda: json.dumps(_record(data=["token"])).encode(),
}


@pytest.mark.parametrize("content", BROKEN_FILES.values(), ids=BROKEN_FILES.keys())
def test_load_treats_a_broken_file_as_a_miss(cache, cache_dir, content):
    """Unparsable, wrongly shaped and expired files are all misses, not errors."""
    cache_dir.mkdir(mode=0o700)
    with open(cache.path("dev"), "wb") as broken:
        broken.write(content())

    assert cache.load("dev") is None


def test_load_checks_required_keys(cache):
    """A record whose data lacks a required key, or has a non-string value for it, is a miss."""
    expires_at = time.time() + 3600
    cache.save("missing", {"accessKeyId": "AKIA"}, expires_at=expires_at)
    cache.save("not-a-string", {"accessKeyId": "AKIA", "sessionToken": 42}, expires_at=expires_at)
    cache.save("complete", {"accessKeyId": "AKIA", "sessionToken": "t"}, expires_at=expires_at)

    required = ("accessKeyId", "sessionToken")
    assert cache.load("missing", required_keys=required) is None
    assert cache.load("not-a-string", required_keys=required) is None
    assert cache.load("complete", required_keys=required) == {"accessKeyId": "AKIA", "sessionToken": "t"}


def test_load_logs_a_miss_at_debug(cache, cache_dir, caplog):
    """A broken file is reported at debug level with its path, and is not an error."""
    cache_dir.mkdir(mode=0o700)
    with open(cache.path("dev"), "w", encoding="utf-8") as broken:
        broken.write("{not json")

    with caplog.at_level(logging.DEBUG, logger="infrahouse_core.aws.credentials_cache"):
        assert cache.load("dev") is None

    misses = [record for record in caplog.records if cache.path("dev") in record.getMessage()]
    assert misses
    assert all(record.levelno == logging.DEBUG for record in misses)


@pytest.mark.parametrize(
    "key",
    [
        "../escape",
        "../../../../../../tmp/escape",
        "/absolute/escape",
        "a/b",
        "..",
        ".",
        "",
        "nul\x00byte",
        "back\\slash",
    ],
)
def test_path_stays_in_the_cache_directory(cache, cache_dir, key):
    """Whatever the key, its file is a hex-named file directly inside the cache directory."""
    path = cache.path(key)

    assert os.path.dirname(path) == str(cache_dir)
    name = os.path.basename(path)
    assert name.startswith(f"{NAMESPACE}-") and name.endswith(".json")
    digest = name[len(NAMESPACE) + 1 : -len(".json")]
    assert len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def test_different_keys_and_namespaces_use_different_files(cache_dir):
    """Two keys in one namespace, or one key in two namespaces, never share a file."""
    first = CredentialsCache("first", directory=str(cache_dir))
    second = CredentialsCache("second", directory=str(cache_dir))
    expires_at = time.time() + 3600

    first.save("dev", {"owner": "first-dev"}, expires_at=expires_at)
    first.save("prod", {"owner": "first-prod"}, expires_at=expires_at)

    assert len({first.path("dev"), first.path("prod"), second.path("dev")}) == 3
    assert first.load("dev") == {"owner": "first-dev"}
    assert first.load("prod") == {"owner": "first-prod"}
    assert second.load("dev") is None


@pytest.mark.parametrize("namespace", ["", "../up", "a/b", "Upper", "with space", "-leading", "trailing-", "a--b"])
def test_namespace_must_be_lowercase_words_and_hyphens(namespace):
    """The namespace is part of every file name, so anything that isn't lowercase-words-and-hyphens is rejected."""
    with pytest.raises(ValueError) as exc_info:
        CredentialsCache(namespace)

    assert repr(namespace) in str(exc_info.value)


def test_save_writes_a_temp_file_in_the_same_directory_then_renames_it(cache, cache_dir):
    """The record is written and fsynced to a temp file next to the cache file, then renamed onto it."""
    calls = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        calls.append(("fsync", fd))
        real_fsync(fd)

    def replace(src, dst):
        calls.append(("replace", src, dst))
        real_replace(src, dst)

    with mock.patch("os.fsync", side_effect=fsync), mock.patch("os.replace", side_effect=replace):
        cache.save("dev", {"token": "t"}, expires_at=time.time() + 3600)

    assert [call[0] for call in calls] == ["fsync", "replace"]
    _, src, dst = calls[1]
    assert os.path.dirname(src) == str(cache_dir)
    assert dst == cache.path("dev")
    assert os.listdir(cache_dir) == [os.path.basename(cache.path("dev"))]


def test_failed_serialisation_leaves_the_previous_file_intact(cache, cache_dir):
    """json.dump fails half-way through: the old record stays readable and no temp file is left behind."""
    cache.save("dev", {"token": "old"}, expires_at=time.time() + 3600)

    with pytest.raises(TypeError):
        cache.save("dev", {"token": "new", "unserialisable": object()}, expires_at=time.time() + 3600)

    assert cache.load("dev") == {"token": "old"}
    assert os.listdir(cache_dir) == [os.path.basename(cache.path("dev"))]


def test_failed_rename_removes_the_temp_file(cache, cache_dir):
    """If the final rename fails, the error propagates and the temp file is removed."""
    cache.save("dev", {"token": "old"}, expires_at=time.time() + 3600)

    with mock.patch("os.replace", side_effect=OSError("rename failed")):
        with pytest.raises(OSError, match="rename failed"):
            cache.save("dev", {"token": "new"}, expires_at=time.time() + 3600)

    assert cache.load("dev") == {"token": "old"}
    assert os.listdir(cache_dir) == [os.path.basename(cache.path("dev"))]


@pytest.mark.parametrize("expires_at", [float("nan"), float("inf")])
def test_save_rejects_a_non_finite_expiry(cache, cache_dir, expires_at):
    """NaN or infinity can't be written as an expiry: a record must expire, and must be strict JSON."""
    with pytest.raises(ValueError):
        cache.save("dev", {"token": "t"}, expires_at=expires_at)

    assert not cache_dir.exists() or os.listdir(cache_dir) == []
