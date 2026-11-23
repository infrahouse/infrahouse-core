#!/usr/bin/env python3
"""
Log in to AWS IAM Identity Center for real with this checkout's ``infrahouse_core``, and check the result.

The unit tests fake AWS. This script runs the real login against your IAM Identity Center, the way ih-aws does:
``get_aws_session()`` for the first profile, which must log in, then for the other profiles, which must not. Then it
checks the token file, that the AWS CLI can use the token, and that botocore can refresh it. See
``docs/manual_testing.rst``.

The script works in a sandbox: a new private HOME with a copy of your AWS config. The login, botocore and the AWS CLI
read and write their token cache there, so your own ``~/.aws/sso/cache`` is neither read nor changed, and every run
starts with no token. The sandbox is deleted at the end, unless ``--keep-sandbox`` is given.

The script prints no secrets: only key names, file modes, expiry times and ARNs.

Usage::

    python scripts/check_sso_login.py [--device-code] PROFILE [PROFILE ...]
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import webbrowser
from configparser import NoOptionError, NoSectionError
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from time import monotonic
from typing import Any, Callable, List, Optional, Tuple
from unittest import mock

import boto3
import botocore
import dateutil.parser
from botocore.credentials import SSOProvider
from botocore.exceptions import BotoCoreError, ClientError
from botocore.tokens import SSOTokenProvider

import infrahouse_core
import infrahouse_core.aws as ih_aws
from infrahouse_core.aws.config import AWSConfig
from infrahouse_core.aws.exceptions import IHAWSException

_CHECKOUT_SRC = Path(__file__).resolve().parent.parent / "src"
# Set in the environment of the child process that runs the checks. The parent process only makes the sandbox.
_SANDBOX_VARIABLE = "CHECK_SSO_LOGIN_SANDBOX"
_REAL_HOME_VARIABLE = "CHECK_SSO_LOGIN_REAL_HOME"
# Removed from the sandbox's environment, so that only the profiles' SSO settings can supply credentials.
_CREDENTIAL_VARIABLES = (
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)
_SSH_VARIABLES = ("SSH_CONNECTION", "SSH_TTY")

_TOKEN_KEYS = ("startUrl", "region", "accessToken", "expiresAt", "clientId", "clientSecret", "registrationExpiresAt")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# botocore refreshes a token that expires within 15 minutes (SSOTokenProvider._REFRESH_WINDOW).
_EXPIRES_SOON = timedelta(minutes=5)
_AWS_CLI_TIMEOUT = 120


class _SetupError(Exception):
    """The checks can't start, e.g. because of a missing profile."""


class _SecondLogin(Exception):
    """get_aws_session() asked for a login that should not have been needed."""


class _Report:
    """Prints the result of each check and counts the failures."""

    def __init__(self) -> None:
        self.failures = 0

    def check(self, passed: bool, expected: str, actual: str = "") -> bool:
        """
        Print one check's result.

        :param passed: Whether the check passed.
        :param expected: What the check expects.
        :param actual: What happened instead, for a failed check.
        :return: ``passed``.
        """
        if passed:
            print(f"PASS  {expected}", flush=True)
        else:
            self.failures += 1
            print(f"FAIL  {expected}" + (f": {actual}" if actual else ""), flush=True)
        return passed

    @staticmethod
    def info(text: str) -> None:
        """
        Print a fact that isn't checked.

        :param text: The fact.
        """
        print(f"INFO  {text}", flush=True)

    @staticmethod
    def skip(text: str) -> None:
        """
        Print a check that didn't run.

        :param text: The check, and why it didn't run.
        """
        print(f"SKIP  {text}", flush=True)


class _LoginGuard:  # pylint: disable=too-few-public-methods
    """
    Stands in for ``aws_sso_login`` inside ``get_aws_session()``: lets the first login run, and stops any other.

    :param login: The real ``aws_sso_login``.
    """

    def __init__(self, login: Callable[..., boto3.Session]) -> None:
        self._login = login
        self.profiles: List[str] = []

    def __call__(self, aws_config: AWSConfig, profile_name: str, **kwargs: Any) -> boto3.Session:
        """
        Log in for the first call; raise for any other.

        :param aws_config: As for ``aws_sso_login``.
        :param profile_name: As for ``aws_sso_login``.
        :param kwargs: As for ``aws_sso_login``.
        :return: The session ``aws_sso_login`` returns.
        :raise _SecondLogin: If a login already ran.
        """
        self.profiles.append(profile_name)
        if len(self.profiles) > 1:
            raise _SecondLogin(profile_name)
        return self._login(aws_config, profile_name, **kwargs)


class _WarningRecorder(logging.Handler):
    """
    Keeps the warnings of one botocore logger, each with the error behind it, so that a failed check can say why.

    botocore logs a failed token refresh at WARNING and goes on with the old token. The script keeps botocore at
    ERROR, so while the recorder is in use, the logger is opened up to WARNING and its records go only here.

    :param name: The logger, e.g. ``botocore.tokens``.
    """

    def __init__(self, name: str) -> None:
        super().__init__(logging.WARNING)
        self.messages: List[str] = []
        self._logger = logging.getLogger(name)
        self._saved = (self._logger.level, self._logger.propagate)

    def __enter__(self) -> "_WarningRecorder":
        """
        Start recording.

        :return: The recorder.
        """
        self._saved = (self._logger.level, self._logger.propagate)
        self._logger.setLevel(logging.WARNING)
        self._logger.propagate = False
        self._logger.addHandler(self)
        return self

    def __exit__(self, *exc_info: Any) -> None:
        """
        Stop recording, and put the logger back as it was.

        :param exc_info: The exception that ended the block, if any.
        """
        self._logger.removeHandler(self)
        self._logger.setLevel(self._saved[0])
        self._logger.propagate = self._saved[1]

    def emit(self, record: logging.LogRecord) -> None:
        """
        Keep the record's message, and the error it carries.

        :param record: A log record of the logger.
        """
        message = record.getMessage()
        error = record.exc_info[1] if record.exc_info else None
        if error is not None:
            message += f" ({type(error).__name__}: {error})"
        self.messages.append(message)


class _FlowRecorder(logging.Handler):
    """Keeps the log lines in which the login says which flow it runs, and why."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.flows: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """
        Keep the record if it names the login flow.

        :param record: A log record from ``infrahouse_core.aws.sso_login``.
        """
        message = record.getMessage()
        if message.startswith("Logging in with the"):
            self.flows.append(message)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Make the sandbox, run the checks in it, and delete it.

    :param argv: Command line arguments, without the program name. Defaults to ``sys.argv[1:]``.
    :return: The exit code: 0 if every check passed, 1 if any failed, 2 if the checks couldn't start, 130
        after Ctrl-C.
    """
    argv = sys.argv[1:] if argv is None else argv
    args = _parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    logging.getLogger("infrahouse_core").setLevel(logging.INFO)
    # As ih-aws without --debug. Otherwise botocore logs a traceback for the missing token before the first login.
    logging.getLogger("botocore").setLevel(logging.ERROR)
    try:
        if _SANDBOX_VARIABLE in os.environ:
            return _run_checks(args, Path(os.environ[_SANDBOX_VARIABLE]), os.environ[_REAL_HOME_VARIABLE])
        return _run_in_sandbox(args, argv)
    except _SetupError as err:
        print(f"Can't run the checks: {err}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        # Both processes get Ctrl-C. The parent has deleted or kept the sandbox on its way out, and says so.
        if _SANDBOX_VARIABLE not in os.environ:
            print("Stopped." if args.keep_sandbox else "Stopped. The sandbox is deleted.", file=sys.stderr)
        return 130


def _parse_args(argv: List[str]) -> argparse.Namespace:
    """
    Parse the command line.

    :param argv: Command line arguments, without the program name.
    :return: The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Log in to AWS IAM Identity Center with this checkout's infrahouse_core, in a sandbox HOME, and check the "
            "result. Your own ~/.aws/sso/cache is neither read nor changed."
        )
    )
    parser.add_argument(
        "profiles",
        nargs="+",
        metavar="PROFILE",
        help=(
            "AWS profiles of one sso-session. The first logs in; the others must connect without another login. "
            "With one profile, the script adds another profile of the same sso-session, if there is one, preferring "
            "one with the same sso_role_name."
        ),
    )
    parser.add_argument(
        "--device-code", action="store_true", help="Log in with the device flow (use_device_code=True)."
    )
    parser.add_argument("--region", help="AWS region for the sessions. Defaults to each profile's region.")
    parser.add_argument(
        "--config",
        default=os.environ.get("AWS_CONFIG_FILE") or "~/.aws/config",
        help="AWS config file to copy into the sandbox. Defaults to $AWS_CONFIG_FILE, then ~/.aws/config.",
    )
    parser.add_argument("--skip-aws-cli", action="store_true", help="Don't check the token with the AWS CLI.")
    parser.add_argument("--skip-refresh", action="store_true", help="Don't check that botocore refreshes the token.")
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Keep the sandbox, with its live SSO token, for more manual checks. Delete it when you are done.",
    )
    return parser.parse_args(argv)


def _run_in_sandbox(args: argparse.Namespace, argv: List[str]) -> int:
    """
    Make a sandbox HOME with a copy of the AWS config, and run this script again in it.

    botocore reads HOME when it is imported (``SSOTokenProvider._SSO_TOKEN_CACHE_DIR``), so the checks run in a new
    process whose HOME is the sandbox from the start.

    :param args: The parsed arguments.
    :param argv: The arguments, to pass on to the child process.
    :return: The child process's exit code.
    :raise _SetupError: If there is no AWS config, or ``infrahouse_core`` isn't this checkout's.
    """
    source_config = Path(args.config).expanduser()
    if not source_config.is_file():
        raise _SetupError(f"there is no AWS config at {source_config}.")
    package = Path(infrahouse_core.__file__).resolve()
    if not package.is_relative_to(_CHECKOUT_SRC):
        raise _SetupError(
            f"this Python imports infrahouse_core from {package.parent}, not from this checkout. "
            "Run the script in this checkout's development virtualenv (make bootstrap)."
        )

    sandbox = Path(tempfile.mkdtemp(prefix="check-sso-login-"))
    aws_dir = sandbox / ".aws"
    try:
        aws_dir.mkdir(mode=0o700)
        shutil.copyfile(source_config, aws_dir / "config")
        env = {name: value for name, value in os.environ.items() if name not in _CREDENTIAL_VARIABLES}
        env.update(
            {
                "HOME": str(sandbox),
                "AWS_CONFIG_FILE": str(aws_dir / "config"),
                "AWS_SHARED_CREDENTIALS_FILE": str(aws_dir / "credentials"),
                _SANDBOX_VARIABLE: str(sandbox),
                _REAL_HOME_VARIABLE: os.path.expanduser("~"),
            }
        )
        return subprocess.run([sys.executable, str(Path(__file__).resolve()), *argv], env=env, check=False).returncode
    finally:
        if args.keep_sandbox:
            _say_kept(sandbox, args.profiles[0])
        else:
            shutil.rmtree(sandbox, ignore_errors=True)


def _say_kept(sandbox: Path, profile: str) -> None:
    """
    Say where the kept sandbox is, whether it holds an SSO token, and how to delete it.

    The run may have stopped before the login saved a token: after Ctrl-C, or a setup error.

    :param sandbox: The sandbox HOME.
    :param profile: A profile to show in the example ``aws`` command.
    """
    cache_dir = sandbox / ".aws" / "sso" / "cache"
    text = f"\nKept the sandbox at {sandbox}."
    if cache_dir.is_dir() and any(cache_dir.glob("*.json")):
        text += (
            " It holds a live SSO token. To use it with the AWS CLI:\n\n"
            f"    HOME={sandbox} AWS_CONFIG_FILE={sandbox / '.aws' / 'config'} aws sts get-caller-identity "
            f"--profile {profile}\n\n"
            "Delete it when you are done:"
        )
    else:
        text += " It holds no SSO token. Delete it when you are done:"
    print(f"{text}\n\n    rm -rf {sandbox}\n", file=sys.stderr)


def _run_checks(args: argparse.Namespace, sandbox: Path, real_home: str) -> int:
    """
    Run every check, in the sandbox.

    :param args: The parsed arguments.
    :param sandbox: The sandbox HOME.
    :param real_home: The user's own HOME, for the web browser.
    :return: 0 if every check passed, 1 if any failed.
    :raise _SetupError: If botocore doesn't use the sandbox, or the profiles don't fit.
    """
    _check_botocore_uses(sandbox)
    config = AWSConfig()
    profiles, session_name = _pick_profiles(config, args.profiles)
    regions = {profile: args.region or config.get_region(profile) or "us-east-1" for profile in profiles}
    token_path = sandbox / ".aws" / "sso" / "cache" / f"{hashlib.sha1(session_name.encode()).hexdigest()}.json"

    print(
        f"infrahouse_core {version('infrahouse-core')} from {Path(infrahouse_core.__file__).parent}, "
        f"botocore {botocore.__version__}, Python {sys.version.split()[0]}.\n"
        f"Sandbox HOME: {sandbox}\n"
        f"sso-session {session_name}: {profiles[0]} logs in"
        + (f"; {', '.join(profiles[1:])} must not.\n" if profiles[1:] else ".\n"),
        flush=True,
    )
    report = _Report()
    flows = _FlowRecorder()
    logging.getLogger("infrahouse_core.aws.sso_login").addHandler(flows)
    guard = _LoginGuard(ih_aws.aws_sso_login)
    with (
        mock.patch.object(ih_aws, "aws_sso_login", guard),
        mock.patch.object(webbrowser, "open", _with_home(webbrowser.open, real_home)),
    ):
        if not _check_login(report, args, config, profiles[0], regions[profiles[0]], guard, flows):
            return 1
        _check_token_file(report, config, profiles[0], token_path)
        _check_other_profiles(report, config, profiles[1:], regions)
    _check_aws_cli(report, args, profiles[-1])
    _check_refresh(report, args, profiles[0], regions[profiles[0]], token_path)

    if report.failures:
        print(f"\n{report.failures} check(s) failed.", flush=True)
        return 1
    print("\nEvery check passed.", flush=True)
    return 0


def _check_botocore_uses(sandbox: Path) -> None:
    """
    Make sure botocore reads SSO tokens from the sandbox, not from the user's own ``~/.aws/sso/cache``.

    :param sandbox: The sandbox HOME.
    :raise _SetupError: If botocore's token cache directory is elsewhere.
    """
    expected = str(sandbox / ".aws" / "sso" / "cache")
    for provider in (SSOTokenProvider, SSOProvider):
        actual = provider._SSO_TOKEN_CACHE_DIR  # pylint: disable=protected-access
        if actual != expected:
            raise _SetupError(f"botocore's {provider.__name__} reads tokens from {actual}, not from the sandbox.")


def _pick_profiles(config: AWSConfig, names: List[str]) -> Tuple[List[str], str]:
    """
    Check that the profiles exist and share one sso-session. With one profile, add another one of its sso-session,
    preferring one with the same ``sso_role_name``, so that the second profile has no more power than the first.

    :param config: The sandbox's AWS config.
    :param names: The profiles from the command line.
    :return: The profiles to check, starting with the one that logs in, and the name of their sso-session.
    :raise _SetupError: If a profile is missing, has no ``sso_session``, or the profiles use different ones.
    """
    unknown = [name for name in names if name not in config.profiles]
    if unknown:
        raise _SetupError(f"no profile {', '.join(unknown)} in the AWS config.")
    sessions = {name: _sso_session(config, name) for name in names}
    for name, session in sessions.items():
        if session is None:
            raise _SetupError(f"profile {name} has no sso_session, and only profiles with one share a token.")
    if len(set(sessions.values())) > 1:
        uses = ", ".join(f"{name} uses {session}" for name, session in sessions.items())
        raise _SetupError(f"the profiles must use one sso-session: {uses}.")

    profiles = list(dict.fromkeys(names))
    session_name = sessions[profiles[0]]
    if len(profiles) == 1:
        others = [
            other for other in config.profiles if other != profiles[0] and _sso_session(config, other) == session_name
        ]
        role = _sso_role_name(config, profiles[0])
        same_role = [other for other in others if _sso_role_name(config, other) == role]
        profiles += (same_role or others)[:1]
    return profiles, session_name


def _sso_session(config: AWSConfig, profile: str) -> Optional[str]:
    """
    Read a profile's ``sso_session``.

    :param config: The AWS config.
    :param profile: The profile.
    :return: The name of its sso-session, or None if it has none.
    """
    try:
        return config.get_sso_session(profile)
    except (NoOptionError, NoSectionError):
        return None


def _sso_role_name(config: AWSConfig, profile: str) -> Optional[str]:
    """
    Read a profile's ``sso_role_name``.

    :param config: The AWS config.
    :param profile: The profile.
    :return: The name of its role, or None if it has none.
    """
    try:
        return config.get_role(profile)
    except (NoOptionError, NoSectionError):
        return None


def _with_home(open_url: Callable[..., bool], home: str) -> Callable[..., bool]:
    """
    Wrap ``webbrowser.open`` so that the browser starts with the user's own HOME, not the sandbox's.

    On Linux, a browser started with the sandbox HOME would not find the user's profile.

    :param open_url: The real ``webbrowser.open``.
    :param home: The user's own HOME.
    :return: The wrapper.
    """

    def open_with_home(url: str, *args: Any, **kwargs: Any) -> bool:
        sandbox_home = os.environ["HOME"]
        os.environ["HOME"] = home
        try:
            return open_url(url, *args, **kwargs)
        finally:
            os.environ["HOME"] = sandbox_home

    return open_with_home


def _check_login(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    report: _Report,
    args: argparse.Namespace,
    config: AWSConfig,
    profile: str,
    region: str,
    guard: _LoginGuard,
    flows: _FlowRecorder,
) -> bool:
    """
    Run ``get_aws_session()`` for the first profile, with no token, and check that it logs in and connects.

    :param report: Where the results go.
    :param args: The parsed arguments.
    :param config: The sandbox's AWS config.
    :param profile: The profile that logs in.
    :param region: The region for its session.
    :param guard: The stand-in for ``aws_sso_login``, which records the login.
    :param flows: The log lines that name the login flow.
    :return: Whether it connected; the other checks need the token.
    """
    started = monotonic()
    try:
        session = ih_aws.get_aws_session(config, profile, region, use_device_code=args.device_code)
        arn = session.client("sts").get_caller_identity()["Arn"]
    # Only the errors of a login that AWS or the user refused. Anything else is a bug that the script is here to find,
    # so it ends the run with its traceback.
    except (IHAWSException, BotoCoreError, ClientError) as err:
        report.check(False, f"{profile}: get_aws_session() logs in and connects", f"{type(err).__name__}: {err}")
        return False

    report.check(guard.profiles == [profile], f"{profile}: get_aws_session() logged in", "no login ran")
    flow = flows.flows[-1] if flows.flows else "No log line named the login flow."
    report.info(f"{flow} It took {monotonic() - started:.0f} s.")
    if args.device_code or any(variable in os.environ for variable in _SSH_VARIABLES):
        report.check("device flow" in flow, "the device flow ran", "another flow ran")
    report.check(True, f"{profile}: connected as {arn}")
    return True


def _check_token_file(report: _Report, config: AWSConfig, profile: str, token_path: Path) -> None:
    """
    Check the token file: its name, its mode, its directories' modes, and its keys and times.

    :param report: Where the results go.
    :param config: The sandbox's AWS config.
    :param profile: The profile that logged in.
    :param token_path: Where botocore looks for the token: ``~/.aws/sso/cache/<sha1 of the sso-session name>.json``.
    """
    cache_dir = token_path.parent
    found = sorted(os.listdir(cache_dir)) if cache_dir.is_dir() else []
    if not report.check(
        token_path.is_file(), f"the token is in ~/.aws/sso/cache/{token_path.name}", f"that folder has {found}"
    ):
        return
    report.check(found == [token_path.name], "it is the only file there", f"that folder has {found}")
    for path, name, mode in (
        (token_path, "the token file", 0o600),
        (cache_dir, "~/.aws/sso/cache", 0o700),
        (cache_dir.parent, "~/.aws/sso", 0o700),
    ):
        actual = stat.S_IMODE(path.stat().st_mode)
        report.check(actual == mode, f"{name} is {mode:04o}", f"it is {actual:04o}")

    token = json.loads(token_path.read_text(encoding="utf-8"))
    missing = [key for key in _TOKEN_KEYS if key not in token]
    report.check(not missing, f"the token has {', '.join(_TOKEN_KEYS)}", f"it has no {', '.join(missing)}")
    report.check(
        token.get("startUrl") == config.get_start_url(profile)
        and token.get("region") == config.get_sso_region(profile),
        "its startUrl and region are the sso-session's",
    )
    report.check(
        "refreshToken" in token,
        "the token has a refreshToken, so botocore can refresh it",
        "it has none, so botocore can't refresh it, and a new login is needed when it expires",
    )
    others = sorted(set(token) - set(_TOKEN_KEYS) - {"refreshToken"})
    if others:
        report.info(f"The token also has {', '.join(others)}.")
    for key in ("expiresAt", "registrationExpiresAt"):
        _check_time(report, token, key)


def _check_time(report: _Report, token: dict, key: str) -> None:
    """
    Check that a time in the token is in botocore's UTC format, and in the future.

    :param report: Where the results go.
    :param token: The token.
    :param key: The key of the time.
    """
    value = token.get(key)
    try:
        when = datetime.strptime(value, _UTC_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        report.check(False, f"{key} is a UTC time like 2026-01-31T23:59:59Z", f"it is {value!r}")
        return
    left = when - datetime.now(timezone.utc)
    report.check(left > timedelta(0), f"{key} is {value}, in {_duration(left)}", "that is in the past")


def _duration(duration: timedelta) -> str:
    """
    Say roughly how long a duration is.

    :param duration: The duration.
    :return: e.g. "89 days" or "7 h 59 min".
    """
    if duration.days >= 2:
        return f"{duration.days} days"
    minutes = int(duration.total_seconds()) // 60
    return f"{minutes // 60} h {minutes % 60} min"


def _check_other_profiles(report: _Report, config: AWSConfig, profiles: List[str], regions: dict) -> None:
    """
    Run ``get_aws_session()`` for the other profiles, and check that they connect with no other login.

    :param report: Where the results go.
    :param config: The sandbox's AWS config.
    :param profiles: The profiles after the first.
    :param regions: The region for each profile's session.
    """
    if not profiles:
        report.skip("the shared-token check: there is no other profile of this sso-session; give two profiles")
        return
    for profile in profiles:
        expected = f"{profile}: get_aws_session() connects with the same token, and no other login"
        try:
            session = ih_aws.get_aws_session(config, profile, regions[profile])
            arn = session.client("sts").get_caller_identity()["Arn"]
        except _SecondLogin:
            report.check(False, expected, "it asked for another login")
        except (BotoCoreError, ClientError) as err:
            report.check(False, expected, f"{type(err).__name__}: {err}")
        else:
            report.check(True, f"{expected}, as {arn}")


def _check_aws_cli(report: _Report, args: argparse.Namespace, profile: str) -> None:
    """
    Check that the AWS CLI finds the token: ``aws sts get-caller-identity`` with the sandbox HOME.

    :param report: Where the results go.
    :param args: The parsed arguments.
    :param profile: The profile to run it with.
    """
    aws = shutil.which("aws")
    if args.skip_aws_cli or aws is None:
        report.skip("the AWS CLI check: " + ("--skip-aws-cli was given" if args.skip_aws_cli else "aws isn't on PATH"))
        return
    expected = f"aws sts get-caller-identity --profile {profile} uses the token"
    try:
        result = subprocess.run(
            [aws, "sts", "get-caller-identity", "--profile", profile, "--output", "json"],
            capture_output=True,
            text=True,
            env=dict(os.environ, AWS_PAGER=""),
            timeout=_AWS_CLI_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        report.check(False, expected, f"it didn't finish in {_AWS_CLI_TIMEOUT} s")
        return
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        report.check(False, expected, lines[-1] if lines else f"it exited with {result.returncode}")
        return
    report.check(True, f"{expected}, as {json.loads(result.stdout)['Arn']}")


def _check_refresh(report: _Report, args: argparse.Namespace, profile: str, region: str, token_path: Path) -> None:
    """
    Make the token expire in 5 minutes, connect with a new session, and check that botocore refreshed the token.

    :param report: Where the results go.
    :param args: The parsed arguments.
    :param profile: The profile that logged in.
    :param region: The region for its session.
    :param token_path: The token file.
    """
    if args.skip_refresh:
        report.skip("the refresh check: --skip-refresh was given")
        return
    if not token_path.is_file():
        report.skip("the refresh check: there is no token file")
        return
    token = json.loads(token_path.read_text(encoding="utf-8"))
    if "refreshToken" not in token:
        report.skip("the refresh check: the token has no refreshToken")
        return

    expires_soon = datetime.now(timezone.utc) + _EXPIRES_SOON
    token["expiresAt"] = expires_soon.strftime(_UTC_FORMAT)
    # Rewritten in place, so that the file keeps its mode.
    with open(token_path, "r+", encoding="utf-8") as token_file:
        json.dump(token, token_file)
        token_file.truncate()

    expected = "botocore refreshes a token that expires in 5 minutes"
    with _WarningRecorder("botocore.tokens") as warnings:
        try:
            boto3.Session(profile_name=profile, region_name=region).client("sts").get_caller_identity()
        except (BotoCoreError, ClientError) as err:
            report.check(False, expected, f"{type(err).__name__}: {err}")
            return
    refreshed = json.loads(token_path.read_text(encoding="utf-8"))
    why = " ".join(warnings.messages) or "botocore logged no warning."
    if not report.check(
        refreshed.get("accessToken") != token["accessToken"], expected, f"the access token didn't change. {why}"
    ):
        return
    report.check(
        dateutil.parser.parse(refreshed["expiresAt"]) > expires_soon,
        f"the new access token expires later, at {refreshed['expiresAt']}",
        "it doesn't",
    )
    mode = stat.S_IMODE(token_path.stat().st_mode)
    report.check(mode == 0o600, "the token file is still 0600", f"it is {mode:04o}")
    if "refreshToken" in refreshed:
        report.info("The refreshed token has a refreshToken too.")
    else:
        report.info("AWS returned no new refreshToken, so botocore dropped it: the next refresh will need a login.")


if __name__ == "__main__":
    sys.exit(main())
