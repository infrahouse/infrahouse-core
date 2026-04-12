# Plan: Fix OOM in GitHubActions.runners / find_runners_by_label

## Context

GitHub issue [infrahouse/infrahouse-core#136](https://github.com/infrahouse/infrahouse-core/issues/136):
`GitHubActions.runners` (property) and `find_runners_by_label()` in `src/infrahouse_core/github.py`
load the entire org's runner list into memory before returning. In a 128 MB Lambda with a large
org, this causes `Runtime.OutOfMemory`.

Current memory cost per call:

1. `_get_github_runners()` builds a Python list with every page's `runners[]` merged (`runners.extend(data["runners"])`).
2. `runners` wraps that list into a second full list of `GitHubActionsRunner` objects via list comprehension.
3. `find_runners_by_label()` calls `self.runners` and materializes a third list via list comprehension.

So for N org runners, peak live objects are ~3N before the caller ever starts processing. Fix is to
stream pages and yield one runner at a time so memory is O(1) (or O(page_size), which is bounded by
the GitHub API — max 100 per page).

## Step 1 — Write a failing test that reproduces the memory problem

File: `tests/github/test_runners_memory.py` (new file).

The test must demonstrate that the current implementation materializes all runners before the
caller can process any of them. The cleanest way to prove this without measuring RSS is to assert
that the iteration is **lazy** — i.e. that consuming only the first element from
`find_runners_by_label()` should not require the HTTP GET for later pages to have completed.

### Test design

Patch `infrahouse_core.github.get` with a `side_effect` function that serves paginated responses.
Each page's mock response exposes a `.links` dict pointing to the next page. Crucially, the mock
tracks how many pages have been fetched in a shared counter.

The test then:

1. Creates a `GitHubActions` instance with a `GitHubAuth` stub.
2. Calls `find_runner_by_label("alpha")` where `"alpha"` is on a runner present in **page 1**.
3. Asserts that `fetched_pages == 1` — i.e. the implementation short-circuited after finding the
   match on the first page and never paged through the rest.

Under the current code, `find_runner_by_label` calls `self.runners`, which calls
`_get_github_runners()`, which eagerly walks every page before returning. The counter will
therefore be `== total_pages` (e.g. 5), not 1, and the assertion fails.

A second test covers `find_runners_by_label` (plural): set up 5 pages where the "alpha" label
appears on page 1 and page 3 only. Consume **only the first element** of the result by calling
`next(iter(gha.find_runners_by_label("alpha")))` and assert that `fetched_pages == 1`. This test
will fail under the current implementation (which returns a `list`, forcing all pages to be
fetched) and pass once the method becomes a generator. It also documents the new contract: the
method returns an iterator, not a list.

A third test is a straightforward correctness check: consume the full iterator and assert the
returned runners' IDs match the expected set across all pages. This guards against the generator
fix accidentally dropping or double-yielding runners.

### Test skeleton

```python
from unittest import mock
import pytest
from infrahouse_core.github import GitHubActions, GitHubAuth


def _make_page(runners, next_url=None):
    resp = mock.Mock()
    resp.json.return_value = {"runners": runners}
    resp.links = {"next": {"url": next_url}} if next_url else {}
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def paginated_get():
    fetched = {"count": 0}

    def _runner(i, labels):
        return {"id": i, "name": f"r{i}", "os": "linux", "status": "online",
                "busy": False, "labels": [{"id": 1, "name": l} for l in labels]}

    pages = [
        [_runner(1, ["alpha"]), _runner(2, ["beta"])],
        [_runner(3, ["gamma"])],
        [_runner(4, ["alpha"]), _runner(5, ["delta"])],
        [_runner(6, ["epsilon"])],
        [_runner(7, ["zeta"])],
    ]
    urls = [f"https://api.github.com/p{i}" for i in range(len(pages))]

    def side_effect(url, headers=None, timeout=None):
        fetched["count"] += 1
        idx = urls.index(url) if url in urls else 0
        next_url = urls[idx + 1] if idx + 1 < len(pages) else None
        return _make_page(pages[idx], next_url)

    with mock.patch("infrahouse_core.github.get", side_effect=side_effect) as m:
        # Seed first URL (the initial fetch uses the org URL, not urls[0])
        yield m, fetched, urls, pages


def test_find_runner_by_label_is_lazy(paginated_get):
    _, fetched, _, _ = paginated_get
    gha = GitHubActions(GitHubAuth("t", "org"))
    runner = gha.find_runner_by_label("alpha")
    assert runner is not None
    assert fetched["count"] == 1  # fails today — eager paging fetches all 5
```

Note: the real initial URL is `https://api.github.com/orgs/{org}/actions/runners`, so the
`side_effect` will need a small tweak to treat that as "page 0" — either by seeding `urls[0]` to
that exact string or by matching on a path prefix.

Run `pytest tests/github/test_runners_memory.py -xvvs` and confirm these tests **fail** against
`main` before moving on.

## Step 2 — Implementation

File: `src/infrahouse_core/github.py`.

### 2a. `_get_github_runners` → generator

```python
def _get_github_runners(self) -> Iterator[dict]:
    url = f"https://api.github.com/orgs/{self._github.org}/actions/runners"
    while url:
        response = get(url, headers=self._github_headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        for runner in data["runners"]:
            yield runner
        url = response.links.get("next", {}).get("url")
```

One page is held in memory at a time. Add `from typing import Iterator` to the imports.

### 2b. `GitHubActions.runners` → generator

```python
@property
def runners(self) -> Iterator[GitHubActionsRunner]:
    for r in self._get_github_runners():
        yield GitHubActionsRunner(r["id"], self._github, runner_data=r)
```

**Type-hint change is a breaking change** at the signature level (was `List[...]`, now
`Iterator[...]`). Callers that do `len(gha.runners)` or `gha.runners[0]` will break. Grep the
codebase for `.runners` usage — the only in-tree call sites are `find_runner_by_label` and
`find_runners_by_label`, both of which iterate, so they are safe. Any external repo consuming
the library that materialized the list needs to call `list(gha.runners)` explicitly; mention
this in the PR description as a minor breaking change.

### 2c. `find_runner_by_label` — already correct

It already uses `next((... for runner in self.runners ...), None)`, so once `runners` is a
generator, it becomes lazy automatically. No code change needed, but the new behavior (stops
paging at first match) is what makes the first test pass.

### 2d. `find_runners_by_label` → generator

```python
def find_runners_by_label(self, label: str) -> Iterator[GitHubActionsRunner]:
    for runner in self.runners:
        if label in runner.labels:
            yield runner
```

Return type changes from `List[GitHubActionsRunner]` to `Iterator[GitHubActionsRunner]`.
Same breaking-change caveat as `runners` — grep for call sites. Known in-tree call site:
`tests/github/test_find_runners_by_label.py` does `len(result)` and `result == []`, which will
break with a generator. Update that test to wrap with `list(...)`:

```python
result = list(gha_instance.find_runners_by_label("any"))
```

Two spots in `test_find_runners_by_label.py` need this adjustment.

## Step 3 — Verify

Re-run the new memory tests:

```bash
pytest tests/github/test_runners_memory.py -xvvs
```

All three should now pass (`fetched["count"] == 1` for the short-circuit tests; correctness test
yields all runners across pages).

Re-run the full github test module to ensure no regression:

```bash
pytest tests/github/ -xvvs
```

Then the whole suite:

```bash
make test
```

## Step 4 — Docs / linting

- Update the docstring example in `GitHubActions` class: the `for runner in gha.runners` loop
  still works unchanged, so no doc change needed there. But add a one-line note that `runners`
  and `find_runners_by_label` return iterators — callers should iterate or wrap with `list()`.
- Run `make lint` before committing.

## Out of scope

- Per-runner boto3 client reuse in `ASGInstance` (the issue mentions it as a contributing factor,
  but it lives outside `github.py` and is a separate optimization).
- Adding a `page_size` knob to `_get_github_runners` — the GitHub default (30) is already small;
  changing it is an orthogonal tuning exercise.
- Caching. Do **not** add caching to the generator — that would re-introduce the memory problem.