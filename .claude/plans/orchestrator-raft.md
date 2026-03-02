# Plan: Orchestrator Raft Management Classes

## Context

GitHub issue [infrahouse/terraform-aws-percona-server#49](https://github.com/infrahouse/terraform-aws-percona-server/issues/49): when ASG replaces Orchestrator instances,
terminated nodes are never removed from the Raft peer list. A Lambda using ASG lifecycle hooks will reconcile
Raft membership. This PR adds the supporting classes in `infrahouse-core` that the Lambda will consume.

## New Files

### 1. `src/infrahouse_core/orchestrator/__init__.py`
Re-exports public API: `OrchestratorRaftNode`, `OrchestratorRaftCluster`, and exception classes.

### 2. `src/infrahouse_core/orchestrator/exceptions.py`
Exception hierarchy mirroring `aws/exceptions.py`:
- `IHOrchestratorException(IHCoreException)` — base
- `IHRaftLeaderNotFound(IHOrchestratorException)` — no leader found
- `IHRaftPeerError(IHOrchestratorException)` — add/remove peer failed

### 3. `src/infrahouse_core/orchestrator/raft_node.py` — `OrchestratorRaftNode`
Wraps a single Orchestrator node's HTTP API. No AWS dependency. Follows `github.py` patterns.

**Constructor:** `(host, http_port=3000, raft_port=10008, protocol="http")`

**Properties:**
- `host` — the node's IP/hostname
- `peer_addr` — `"{host}:{raft_port}"` string used in Raft membership
- `raft_peers` — `GET /api/raft-peers`, returns `List[str]`, cached with TTL=10
- `raft_leader` — `GET /api/raft-leader`, returns `Optional[str]` (None if "nil"/empty), cached with TTL=10
- `raft_health` — `GET /api/raft-health`, returns `dict`, cached with TTL=10
- `is_leader` — compares `raft_leader` to own `peer_addr`

**Methods:**
- `add_peer(addr)` — `GET /api/raft-add-peer/{addr}`, raises `IHRaftPeerError` on application-level error
- `remove_peer(addr)` — `GET /api/raft-remove-peer/{addr}`, same error handling
- `_url(path)` — private, builds full URL
- `_check_raft_response(response, operation)` — static, inspects `{"Code": "ERROR"}` body

Uses `from requests import get` at module level, explicit timeouts (5s reads, 10s mutations), `response.raise_for_status()`.

### 4. `src/infrahouse_core/orchestrator/raft_cluster.py` — `OrchestratorRaftCluster`
Ties Raft membership to ASG. Composes an `ASG` instance (not inheritance).

**Constructor:** `(asg_name, region=None, role_arn=None, session=None, http_port=3000, raft_port=10008, protocol="http")`

**Properties:**
- `nodes` — creates `OrchestratorRaftNode` per live ASG instance (from `ASG.instances` private IPs)
- `leader` — queries each node for `raft_leader`, returns the leader `OrchestratorRaftNode`; skips unreachable nodes; raises `IHRaftLeaderNotFound` if none found
- `peers` — `leader.raft_peers`
- `_asg` — lazy-created `ASG` instance with session propagation

**Methods:**
- `add_peer(ip)` — builds `"{ip}:{raft_port}"`, calls `leader.add_peer()`
- `remove_peer(ip)` — builds `"{ip}:{raft_port}"`, calls `leader.remove_peer()`
- `reconcile()` — compares ASG IPs vs Raft peer IPs, removes stale, adds missing

### 5. `tests/orchestrator/__init__.py` — empty

### 6. `tests/orchestrator/test_raft_node.py`
Mocks `infrahouse_core.orchestrator.raft_node.get` at module level (same as `test_github.py`).

Test cases:
- `test_peer_addr` — pure computation
- `test_raft_peers` / `test_raft_leader` / `test_raft_health` — mock HTTP responses
- `test_raft_leader_nil` / `test_raft_leader_empty` — returns None
- `test_is_leader_true` / `test_is_leader_false`
- `test_add_peer_success` / `test_add_peer_error` — checks `IHRaftPeerError`
- `test_remove_peer_success` / `test_remove_peer_http_error`
- `test_url_construction` / `test_url_construction_https`

### 7. `tests/orchestrator/test_raft_cluster.py`
Mocks `ASG.instances`, `OrchestratorRaftCluster.leader`, `OrchestratorRaftCluster._asg` as needed.

Test cases:
- `test_nodes_from_asg` — patches ASG.instances, verifies node creation
- `test_leader_found` / `test_leader_not_found` / `test_leader_skips_unreachable`
- `test_add_peer` / `test_remove_peer` — delegates to leader
- `test_reconcile_removes_stale` / `test_reconcile_adds_missing` / `test_reconcile_no_changes` / `test_reconcile_both`
- `test_reconcile_raises_on_error`
- `test_asg_session_propagated` / `test_asg_lazy_created_once`

## Modified Files

### 8. `pyproject.toml`
Add `"requests ~= 2.32"` to `dependencies` (currently used but only as transitive dep).

## Implementation Order

1. `pyproject.toml` — add requests dependency
2. `src/infrahouse_core/orchestrator/exceptions.py`
3. `src/infrahouse_core/orchestrator/raft_node.py`
4. `src/infrahouse_core/orchestrator/raft_cluster.py`
5. `src/infrahouse_core/orchestrator/__init__.py`
6. `tests/orchestrator/__init__.py`
7. `tests/orchestrator/test_raft_node.py`
8. `tests/orchestrator/test_raft_cluster.py`

## Key Patterns to Follow

- **HTTP calls:** `from requests import get` at module level, explicit `timeout=`, `response.raise_for_status()` (from `github.py`)
- **Caching:** `@cached_property_with_ttl(ttl=10)` for API response properties (from `github.py`, `ec2_instance.py`)
- **Lazy ASG:** sentinel `None` + property, session-first pattern (from `asg.py`)
- **Exceptions:** inherit from `IHCoreException`, same docstring style as `aws/exceptions.py`
- **Test imports:** use `infrahouse_core.orchestrator.*` (not `src.infrahouse_core.*`)
- **Test mocking:** `mock.patch("infrahouse_core.orchestrator.raft_node.get")` for HTTP, `mock.patch.object(Class, "prop", new_callable=mock.PropertyMock)` for properties

## Verification

```bash
make test          # all tests pass including new orchestrator tests
make lint          # black, isort, pylint pass
pytest -xvvs tests/orchestrator/   # run just the new tests
```
