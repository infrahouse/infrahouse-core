"""
Tests for retries of GitHub REST API calls (https://github.com/infrahouse/infrahouse-core/issues/23).

These tests run the real requests and urllib3 retry code against a local HTTP server. The failure in the issue
is a connection that GitHub closed without a response, which a mock of the session can't reproduce.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Iterator, List, Optional, Tuple
from unittest import mock

import pytest
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError, ReadTimeout

from infrahouse_core import github
from infrahouse_core.github import GitHubActions, GitHubActionsRunner, GitHubAuth

ORG = "test-org"
RUNNERS_PATH = f"/orgs/{ORG}/actions/runners"

Action = Callable[[BaseHTTPRequestHandler], None]


def _runner(runner_id: int) -> dict:
    return {
        "id": runner_id,
        "name": f"runner{runner_id}",
        "os": "linux",
        "status": "online",
        "busy": False,
        "labels": [{"id": 1, "name": "self-hosted", "type": "read-only"}],
    }


def drop() -> Action:
    """
    Close the connection without sending a response.

    The client sees ``RemoteDisconnected('Remote end closed connection without response')``, as in the issue.
    """

    def action(handler: BaseHTTPRequestHandler) -> None:
        handler.close_connection = True

    return action


def stall(seconds: float) -> Action:
    """
    Read the request, wait ``seconds`` without answering, then close the connection.

    A client whose read timeout is shorter than ``seconds`` times out waiting for the response.
    """

    def action(handler: BaseHTTPRequestHandler) -> None:
        time.sleep(seconds)
        handler.close_connection = True

    return action


def respond(status: int, body: Optional[dict] = None, headers: Optional[Dict[str, str]] = None) -> Action:
    """
    Send a response with a JSON body. A 204 response has no body.
    """

    def action(handler: BaseHTTPRequestHandler) -> None:
        payload = b"" if status == 204 else json.dumps(body if body is not None else {}).encode()
        handler.send_response(status)
        if status != 204:
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(payload)))
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(payload)

    return action


class FakeGitHub(ThreadingHTTPServer):
    """
    A local HTTP server that answers requests from a script.

    Each request takes the next action from ``actions``. When the script is used up, requests get
    ``default_action``. Every request is recorded in ``requests`` as ``(method, path)``.
    """

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.actions: List[Action] = []
        self.default_action: Action = respond(500, {"message": "the test script ran out of responses"})
        self.requests: List[Tuple[str, str]] = []
        self.lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def script(self, *actions: Action) -> None:
        self.actions.extend(actions)


class _Handler(BaseHTTPRequestHandler):
    server: FakeGitHub

    def _handle(self) -> None:
        with self.server.lock:
            self.server.requests.append((self.command, self.path))
            action = self.server.actions.pop(0) if self.server.actions else self.server.default_action
        action(self)

    do_GET = _handle
    do_POST = _handle
    do_DELETE = _handle

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Keep the server quiet."""


@pytest.fixture
def fake_github() -> Iterator[FakeGitHub]:
    """
    Start a local server, point the module at it, and make the retry backoff zero.

    The session is cached for the process, so the fixture drops it before and after the test. That way the test
    gets a session built for the local server, and later tests don't get a session with zero backoff.
    """
    server = FakeGitHub()
    # A short poll interval keeps shutdown() fast; the default 0.5 s would add half a second to every test.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    github._get_session.cache_clear()
    try:
        with (
            mock.patch.object(github, "_GITHUB_API_URL", server.base_url),
            mock.patch.object(github, "_RETRY_BACKOFF_FACTOR", 0),
        ):
            yield server
    finally:
        github._get_session.cache_clear()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def gha() -> GitHubActions:
    return GitHubActions(GitHubAuth("test-token", ORG))


# The two kinds of transient failure: urllib3 retries a dropped connection on its read-error path and a 503 on its
# status path.
TRANSIENT_FAILURES = [
    pytest.param(drop(), id="dropped-connection"),
    pytest.param(respond(503), id="503"),
]


def _wait_for_requests(server: FakeGitHub, count: int) -> None:
    """
    Wait up to 2 seconds for the server to record ``count`` requests.

    A client that times out can give up before the server thread has recorded the request it sent.
    """
    deadline = time.monotonic() + 2
    while len(server.requests) < count and time.monotonic() < deadline:
        time.sleep(0.01)


def test_runners_retried_after_dropped_connection(fake_github, gha):
    """The issue's failure: GitHub closes the connection without a response, then answers."""
    fake_github.script(drop(), respond(200, {"runners": [_runner(1)]}))

    runners = list(gha.runners)

    assert [r.runner_id for r in runners] == [1]
    assert fake_github.requests == [("GET", RUNNERS_PATH)] * 2


def test_runners_retried_after_503(fake_github, gha):
    fake_github.script(respond(503), respond(200, {"runners": [_runner(1)]}))

    assert [r.runner_id for r in gha.runners] == [1]
    assert fake_github.requests == [("GET", RUNNERS_PATH)] * 2


def test_429_without_retry_after_is_retried(fake_github, gha):
    """429 is retried because it is in the status forcelist, not only because of a Retry-After header."""
    fake_github.script(respond(429, {"message": "rate limited"}), respond(200, {"runners": [_runner(1)]}))

    assert [r.runner_id for r in gha.runners] == [1]
    assert fake_github.requests == [("GET", RUNNERS_PATH)] * 2


def test_429_retry_after_header_is_honoured(fake_github, gha):
    """The retry waits as long as Retry-After says. The backoff is zero in these tests, so only Retry-After sleeps."""
    fake_github.script(
        respond(429, {"message": "secondary rate limit"}, headers={"Retry-After": "3"}),
        respond(200, {"runners": [_runner(1)]}),
    )

    with mock.patch("urllib3.util.retry.time.sleep") as sleep:
        assert [r.runner_id for r in gha.runners] == [1]

    sleep.assert_called_once_with(3)
    assert fake_github.requests == [("GET", RUNNERS_PATH)] * 2


def test_gives_up_on_persistent_503(fake_github, gha):
    """After the last retry the 503 reaches raise_for_status(), so the caller gets HTTPError as before."""
    fake_github.default_action = respond(503)

    with pytest.raises(HTTPError) as err:
        list(gha.runners)

    assert err.value.response.status_code == 503
    assert len(fake_github.requests) == github._RETRY_TOTAL + 1


def test_gives_up_on_persistent_dropped_connection(fake_github, gha):
    """After the last retry a network error reaches the caller as requests.ConnectionError, as before."""
    fake_github.default_action = drop()

    with pytest.raises(RequestsConnectionError):
        list(gha.runners)

    assert len(fake_github.requests) == github._RETRY_TOTAL + 1


def test_gives_up_on_persistent_read_timeout(fake_github):
    """
    After the last retry a read timeout reaches the caller as requests.ReadTimeout, as it did without retries.

    requests itself would report it as ConnectionError, which ``except requests.Timeout`` doesn't catch.
    """
    fake_github.default_action = stall(0.3)

    with pytest.raises(ReadTimeout) as err:
        github._request("GET", f"{fake_github.base_url}{RUNNERS_PATH}", headers={}, timeout=0.05)

    assert not isinstance(err.value, RequestsConnectionError)
    _wait_for_requests(fake_github, github._RETRY_TOTAL + 1)
    assert len(fake_github.requests) == github._RETRY_TOTAL + 1


@pytest.mark.parametrize("status", [401, 404])
def test_client_errors_not_retried(fake_github, gha, status):
    fake_github.default_action = respond(status, {"message": "nope"})

    with pytest.raises(HTTPError) as err:
        list(gha.runners)

    assert err.value.response.status_code == status
    assert fake_github.requests == [("GET", RUNNERS_PATH)]


def test_pagination_retries_failed_page(fake_github, gha):
    """A page that fails is retried on its own: every runner is yielded once, none skipped or repeated."""

    def page(runner_ids: List[int], next_page: Optional[int]) -> Action:
        headers = {"Link": f'<{fake_github.base_url}{RUNNERS_PATH}?page={next_page}>; rel="next"'} if next_page else {}
        return respond(200, {"runners": [_runner(i) for i in runner_ids]}, headers=headers)

    fake_github.script(
        page([1, 2], next_page=2),
        drop(),
        page([3, 4], next_page=3),
        page([5], next_page=None),
    )

    assert [r.runner_id for r in gha.runners] == [1, 2, 3, 4, 5]
    assert fake_github.requests == [
        ("GET", RUNNERS_PATH),
        ("GET", f"{RUNNERS_PATH}?page=2"),
        ("GET", f"{RUNNERS_PATH}?page=2"),
        ("GET", f"{RUNNERS_PATH}?page=3"),
    ]


@pytest.mark.parametrize("failure", TRANSIENT_FAILURES)
def test_deregister_runner_retried(fake_github, gha, failure):
    fake_github.script(failure, respond(204))
    runner = GitHubActionsRunner(7, gha._github, runner_data=_runner(7))

    gha.deregister_runner(runner)

    assert fake_github.requests == [("DELETE", f"{RUNNERS_PATH}/7")] * 2


def test_deregister_runner_404_after_lost_response(fake_github, gha):
    """
    GitHub deleted the runner but the response was lost. The retry gets 404, and deregister_runner() raises
    HTTPError, as its docstring says. This pins the contract the PR keeps (decision 3).
    """
    fake_github.script(drop(), respond(404, {"message": "Not Found"}))
    runner = GitHubActionsRunner(7, gha._github, runner_data=_runner(7))

    with pytest.raises(HTTPError) as err:
        gha.deregister_runner(runner)

    assert err.value.response.status_code == 404
    assert fake_github.requests == [("DELETE", f"{RUNNERS_PATH}/7")] * 2


@pytest.mark.parametrize("failure", TRANSIENT_FAILURES)
def test_registration_token_retried(fake_github, gha, failure):
    fake_github.script(failure, respond(201, {"token": "reg-token", "expires_at": "2026-11-23T20:00:00Z"}))

    assert gha.registration_token == "reg-token"
    assert fake_github.requests == [("POST", f"{RUNNERS_PATH}/registration-token")] * 2


def test_runner_data_retried_after_dropped_connection(fake_github):
    fake_github.script(drop(), respond(200, _runner(9)))

    runner = GitHubActionsRunner(9, GitHubAuth("test-token", ORG))

    assert runner.name == "runner9"
    assert fake_github.requests == [("GET", f"{RUNNERS_PATH}/9")] * 2


def test_get_org_name_retried_after_503(fake_github):
    fake_github.script(respond(503), respond(200, {"id": 42, "account": {"login": ORG}}))
    github_client = mock.Mock()
    github_client.create_jwt.return_value = "test-jwt"

    assert github._get_org_name(github_client, 42) == ORG
    assert fake_github.requests == [("GET", "/app/installations/42")] * 2


def test_get_org_name_raises_http_error(fake_github):
    """An error response raises HTTPError, not a KeyError from reading a body without "account"."""
    fake_github.default_action = respond(404, {"message": "Not Found"})
    github_client = mock.Mock()
    github_client.create_jwt.return_value = "test-jwt"

    with pytest.raises(HTTPError) as err:
        github._get_org_name(github_client, 42)

    assert err.value.response.status_code == 404
    assert fake_github.requests == [("GET", "/app/installations/42")]


def test_session_is_created_once(fake_github):
    assert github._get_session() is github._get_session()
