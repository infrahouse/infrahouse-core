"""
Expiring credentials cached as JSON files in a directory only the user can read.

:func:`infrahouse_core.aws.aws_sso_login` keeps each profile's SSO role credentials here, so the next
call for the same profile doesn't ask for another SSO approval.

A cache file is parsed with :func:`json.load` and its shape is checked before anything in it is used.
Nothing in a cache file can run code when it is read.
"""

import hashlib
import json
import math
import os
import re
import tempfile
import time
from contextlib import suppress
from logging import getLogger
from os import path as osp
from typing import Iterable, Optional

from infrahouse_core.fs import ensure_permissions

LOG = getLogger(__name__)

DEFAULT_CACHE_DIRECTORY = "~/.infrahouse-toolkit"
"""Where InfraHouse tools cache credentials."""

DEFAULT_EXPIRY_MARGIN = 300
"""A record that expires within this many seconds counts as expired already."""

RECORD_VERSION = 1
"""Version of the JSON layout. A file with any other version is a miss."""

_NAMESPACE_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class CredentialsCache:
    """
    Expiring records, one JSON file per key, in a directory readable by its owner only.

    A record is a dict plus the time it expires. :meth:`load` returns the dict, or ``None`` when the file is
    missing, isn't JSON, has the wrong shape or expires within ``expiry_margin`` seconds. On ``None`` the caller
    gets fresh credentials and calls :meth:`save`, which replaces the file.

    A key's file is ``<namespace>-<SHA-256 of the key>.json`` in ``directory``. Keys (AWS profile names, for
    example) are user input, so they reach the filesystem only as a hex digest: no ``/`` or ``..`` in a key can
    point outside the directory. The key itself is stored inside the file, and a file whose stored key differs is
    a miss.

    The directory is created with mode 0700, and set to 0700 if it has other permissions, before every read and
    write. Files are written with mode 0600.

    :param namespace: What this cache holds, e.g. ``sso-role-credentials``. Every file name starts with it, so
        caches with different namespaces never share a file. Lowercase letters and digits, in words joined by
        single hyphens.
    :type namespace: str
    :param directory: The cache directory. A leading ``~`` is expanded.
    :type directory: str
    :param expiry_margin: Seconds before its expiry when a record already counts as expired.
    :type expiry_margin: int
    :raise ValueError: If ``namespace`` isn't lowercase words joined by hyphens.
    """

    def __init__(
        self,
        namespace: str,
        directory: str = DEFAULT_CACHE_DIRECTORY,
        expiry_margin: int = DEFAULT_EXPIRY_MARGIN,
    ) -> None:
        if not _NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError(
                f"Cache namespace must be lowercase letters and digits in words joined by single hyphens, "
                f"got {namespace!r}"
            )
        self._namespace = namespace
        self._directory = osp.expanduser(directory)
        self._expiry_margin = expiry_margin

    def load(self, key: str, required_keys: Iterable[str] = ()) -> Optional[dict]:
        """
        Read the record for a key.

        Every reason the record can't be used is logged at debug level and returns ``None``: the caller is
        expected to get fresh credentials and :meth:`save` them, which replaces the file.

        :param key: The record's key, e.g. an AWS profile name.
        :type key: str
        :param required_keys: Keys the record's data must have, each with a string value.
        :type required_keys: Iterable[str]
        :return: The data saved for the key, or ``None`` if the record is missing, can't be parsed, has the
            wrong shape or expires within the expiry margin.
        :rtype: dict or None
        :raise OSError: If the directory can't be created or its permissions set, or the file exists but
            can't be read.
        """
        self._ensure_directory()
        path = self.path(key)
        try:
            with open(path, encoding="utf-8") as cache_file:
                record = json.load(cache_file)
        except FileNotFoundError:
            LOG.debug("Cache miss for %r: %s doesn't exist", key, path)
            return None
        # json.JSONDecodeError and UnicodeDecodeError are both ValueErrors.
        except ValueError as err:
            LOG.debug("Cache miss for %r: %s isn't valid JSON: %s", key, path, err)
            return None

        problem = self._find_problem(record, key, tuple(required_keys))
        if problem:
            LOG.debug("Cache miss for %r: %s %s", key, path, problem)
            return None

        LOG.debug("Cache hit for %r: %s", key, path)
        return record["data"]

    def path(self, key: str) -> str:
        """
        Path of the file that holds a key's record. The file may not exist.

        :param key: The record's key.
        :type key: str
        :return: ``<directory>/<namespace>-<SHA-256 of the key>.json``
        :rtype: str
        """
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return osp.join(self._directory, f"{self._namespace}-{digest}.json")

    def save(self, key: str, data: dict, expires_at: float) -> None:
        """
        Write the record for a key, replacing any earlier one.

        The record goes to a temp file in the cache directory, created with mode 0600, which is flushed,
        fsynced and then renamed onto the final name. A reader sees the old file or the new one, never a
        partly written file. If anything fails, the temp file is removed and the error propagates.

        :param key: The record's key, e.g. an AWS profile name.
        :type key: str
        :param data: What to cache. Must be serialisable as strict JSON.
        :type data: dict
        :param expires_at: When the data expires, in seconds since the epoch.
        :type expires_at: float
        :raise ValueError: If ``expires_at`` isn't a finite number, or ``data`` holds NaN or infinity.
        :raise TypeError: If ``data`` holds something JSON can't represent.
        :raise OSError: If the directory or the file can't be written.
        """
        if not _is_finite_number(expires_at):
            raise ValueError(f"expires_at must be a finite number of seconds since the epoch, got {expires_at!r}")

        self._ensure_directory()
        path = self.path(key)
        record = {"version": RECORD_VERSION, "key": key, "expires_at": expires_at, "data": data}

        # mkstemp creates the file with mode 0600, whatever the umask.
        file_descriptor, temp_path = tempfile.mkstemp(dir=self._directory, prefix=f".{self._namespace}-", suffix=".tmp")
        renamed = False
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
                json.dump(record, temp_file, allow_nan=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
            renamed = True
        finally:
            if not renamed:
                with suppress(FileNotFoundError):
                    os.unlink(temp_path)

        LOG.debug("Cached a record for %r in %s, expiring at %d", key, path, expires_at)

    def _ensure_directory(self) -> None:
        """Create the cache directory with mode 0700, or set it to 0700 if it exists with other permissions."""
        os.makedirs(self._directory, mode=0o700, exist_ok=True)
        ensure_permissions(self._directory, 0o700)

    def _find_problem(self, record: object, key: str, required_keys: tuple) -> Optional[str]:
        """
        Check the shape and the expiry of a parsed cache file.

        :return: Why the record can't be used, or ``None`` if it can.
        """
        # Each check relies on the ones before it: record is a dict, expires_at a number, data a dict.
        problem = None
        if not isinstance(record, dict):
            problem = f"holds a JSON {type(record).__name__}, not an object"
        elif record.get("version") != RECORD_VERSION:
            problem = f"has version {record.get('version')!r}, expected {RECORD_VERSION}"
        elif record.get("key") != key:
            problem = "holds a record for a different key"
        elif not _is_finite_number(record.get("expires_at")):
            problem = "has no valid expires_at"
        elif not isinstance(record.get("data"), dict):
            problem = "has no data object"
        elif missing := [name for name in required_keys if not isinstance(record["data"].get(name), str)]:
            problem = f"has no string value for {', '.join(missing)}"
        elif (remaining := record["expires_at"] - time.time()) <= self._expiry_margin:
            problem = f"expires in {remaining:.0f} seconds, within the {self._expiry_margin}-second margin"
        return problem


def _is_finite_number(value: object) -> bool:
    """True for an int or float that isn't NaN or infinite. JSON ``true`` loads as a bool, which isn't a number here."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
