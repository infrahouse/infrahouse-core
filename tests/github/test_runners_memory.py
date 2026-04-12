"""
Regression tests for https://github.com/infrahouse/infrahouse-core/issues/136.

These tests assert that GitHubActions.runners / find_runner_by_label /
find_runners_by_label iterate lazily over paginated GitHub API responses
instead of materializing every page before returning.
"""

from unittest import mock

import pytest
from requests import HTTPError

from infrahouse_core.github import GitHubActions, GitHubAuth

ORG = "test-org"
BASE_URL = f"https://api.github.com/orgs/{ORG}/actions/runners"


def _runner(runner_id, label_names):
    return {
        "id": runner_id,
        "name": f"runner{runner_id}",
        "os": "linux",
        "status": "online",
        "busy": False,
        "labels": [{"id": i, "name": n, "type": "custom"} for i, n in enumerate(label_names)],
    }


def _make_response(runners, next_url):
    resp = mock.Mock()
    resp.json.return_value = {"runners": runners}
    resp.links = {"next": {"url": next_url}} if next_url else {}
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def paginated_get():
    """
    Simulate 5 pages of GitHub runners. Page 1 has the "alpha" label; page 3
    also has "alpha". Pages 2/4/5 do not. The fixture tracks how many pages
    have been fetched so tests can assert laziness.
    """
    pages = [
        [_runner(1, ["alpha"]), _runner(2, ["beta"])],
        [_runner(3, ["gamma"])],
        [_runner(4, ["alpha"]), _runner(5, ["delta"])],
        [_runner(6, ["epsilon"])],
        [_runner(7, ["zeta"])],
    ]
    page_urls = [BASE_URL] + [f"https://api.github.com/p{i}" for i in range(1, len(pages))]
    state = {"fetched": 0}

    def side_effect(url, headers=None, timeout=None):
        state["fetched"] += 1
        if url not in page_urls:
            pytest.fail(f"Unexpected URL requested by _get_github_runners: {url!r}")
        idx = page_urls.index(url)
        next_url = page_urls[idx + 1] if idx + 1 < len(pages) else None
        return _make_response(pages[idx], next_url)

    with mock.patch("infrahouse_core.github.get", side_effect=side_effect):
        yield state, pages


def test_find_runner_by_label_stops_at_first_page(paginated_get):
    """
    A single match on page 1 must not cause pages 2-5 to be fetched.
    Fails under the current eager implementation because _get_github_runners
    walks every page before returning.
    """
    state, _ = paginated_get
    gha = GitHubActions(GitHubAuth("test-token", ORG))

    runner = gha.find_runner_by_label("alpha")

    assert runner is not None
    assert runner.runner_id == 1
    assert state["fetched"] == 1


def test_find_runners_by_label_is_lazy(paginated_get):
    """
    Consuming only the first element of find_runners_by_label must not
    force all pages to be fetched. This locks in the generator contract.
    """
    state, _ = paginated_get
    gha = GitHubActions(GitHubAuth("test-token", ORG))

    first = next(iter(gha.find_runners_by_label("alpha")))

    assert first.runner_id == 1
    assert state["fetched"] == 1


def test_runners_yields_all_across_all_pages(paginated_get):
    """
    Direct end-to-end correctness anchor for the ``runners`` property: all
    7 runner IDs across all 5 pages must be yielded exactly once, in order,
    and all 5 pages must be fetched.
    """
    state, pages = paginated_get
    gha = GitHubActions(GitHubAuth("test-token", ORG))

    runner_ids = [r.runner_id for r in gha.runners]

    assert runner_ids == [1, 2, 3, 4, 5, 6, 7]
    assert state["fetched"] == len(pages)


def test_find_runners_by_label_yields_all_matches(paginated_get):
    """
    Correctness guard: a full consumption must yield every matching runner
    across all pages with no duplicates or drops.
    """
    state, pages = paginated_get
    gha = GitHubActions(GitHubAuth("test-token", ORG))

    matches = list(gha.find_runners_by_label("alpha"))

    assert [r.runner_id for r in matches] == [1, 4]
    assert state["fetched"] == len(pages)


def test_get_github_runners_raises_on_missing_runners_key():
    """
    If the GitHub API returns a response without the ``runners`` key,
    ``_get_github_runners`` must fail fast with a ValueError that names
    the keys that *were* present, rather than bubbling up a KeyError
    from somewhere deep in the iteration.
    """
    bogus = mock.Mock()
    bogus.json.return_value = {"total_count": 0}  # no "runners" key
    bogus.links = {}
    bogus.raise_for_status.return_value = None

    with mock.patch("infrahouse_core.github.get", return_value=bogus):
        gha = GitHubActions(GitHubAuth("test-token", ORG))
        with pytest.raises(ValueError, match="'runners' key missing"):
            list(gha.runners)


def test_http_error_on_second_page_raises():
    """
    Page 1 succeeds and its runners are yielded to the caller. Page 2 then
    returns a 5xx — the generator must propagate the HTTPError on the next
    advance instead of swallowing it or silently truncating the iteration.
    """
    page1 = _make_response([_runner(1, ["alpha"])], next_url="https://api.github.com/p1")
    page2 = mock.Mock()
    page2.raise_for_status.side_effect = HTTPError("503 Service Unavailable")

    responses = iter([page1, page2])

    with mock.patch("infrahouse_core.github.get", side_effect=lambda *a, **kw: next(responses)):
        gha = GitHubActions(GitHubAuth("test-token", ORG))
        gen = iter(gha.runners)

        first = next(gen)
        assert first.runner_id == 1

        with pytest.raises(HTTPError):
            next(gen)


def test_get_github_runners_empty_org():
    """
    An org with zero runners returns ``{"runners": []}`` and must yield
    nothing without raising. Guards against regressing the empty-org path.
    """
    empty = mock.Mock()
    empty.json.return_value = {"runners": []}
    empty.links = {}
    empty.raise_for_status.return_value = None

    with mock.patch("infrahouse_core.github.get", return_value=empty):
        gha = GitHubActions(GitHubAuth("test-token", ORG))
        assert list(gha.runners) == []
        assert gha.find_runner_by_label("anything") is None
        assert list(gha.find_runners_by_label("anything")) == []
