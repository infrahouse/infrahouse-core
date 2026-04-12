============
Architecture
============

Module Overview
===============

InfraHouse Core is organized into two main areas:

- **aws** -- AWS service wrappers with consistent session, credential, and role-assumption handling.
- **github** -- GitHub Actions runner management via the GitHub API.

Supporting modules provide logging, timeouts, filesystem helpers, and input validation.

::

    infrahouse_core/
    ├── aws/
    │   ├── __init__.py          # get_session, get_client, get_resource, SSO login
    │   ├── base.py              # AWSResource base class
    │   ├── ec2_instance.py      # EC2 + SSM command execution
    │   ├── dynamodb.py          # DynamoDB table + distributed locking
    │   ├── secretsmanager.py    # Secrets Manager wrapper
    │   ├── route53/zone.py      # DNS record management
    │   ├── config.py            # ~/.aws/config parser
    │   └── ...                  # ACM, CloudFront, ECS, IAM, S3, etc.
    ├── orchestrator/            # RAFT cluster coordination
    ├── github.py                # GitHub Actions runner management
    ├── logging.py               # stdout/stderr log routing
    ├── timeout.py               # SIGALRM-based timeout context manager
    └── validation.py            # Input validation helpers


Session, Client, and Resource Functions
=======================================

The ``aws`` module provides three functions for obtaining boto3 objects.
All three accept optional ``role_arn`` and ``region`` parameters.

``get_session(role_arn=None, region=None)``
    Returns a ``boto3.Session``, optionally with assumed-role credentials.
    Use this when you need to create multiple clients or resources from
    the same set of credentials.

``get_client(service_name, role_arn=None, region=None)``
    Convenience wrapper -- creates a session and returns a single low-level
    client (e.g. ``get_client("ec2")``).

``get_resource(service_name, role_arn=None, region=None)``
    Convenience wrapper -- creates a session and returns a single high-level
    resource (e.g. ``get_resource("dynamodb")``).

**When to use which:**

- Use ``get_client`` (the most common case) when you need one service client.
- Use ``get_resource`` when you want the higher-level boto3 resource API
  (DynamoDB Table, S3 Bucket, etc.).
- Use ``get_session`` when you need to create multiple clients/resources
  sharing the same assumed-role credentials.

Example::

    from infrahouse_core.aws import get_client, get_resource, get_session

    # Single client
    ec2 = get_client("ec2", region="us-east-1")

    # Single resource
    table = get_resource("dynamodb").Table("my-table")

    # Shared session for cross-account access
    session = get_session(role_arn="arn:aws:iam::123456789012:role/MyRole")
    ec2 = session.client("ec2")
    ssm = session.client("ssm")


Role Assumption
===============

Cross-account (or cross-role) access is supported throughout the library
via an optional ``role_arn`` parameter.

**At the function level:**

::

    client = get_client("s3", role_arn="arn:aws:iam::123456789012:role/S3Reader")

**At the class level:**

Most resource classes (``EC2Instance``, ``DynamoDBTable``, ``Secret``, ``Zone``, etc.)
accept ``role_arn`` in their constructors.  The role is assumed lazily when the
first API call is made::

    from infrahouse_core.aws.secretsmanager import Secret

    # Read a secret from another account
    secret = Secret("my-secret", role_arn="arn:aws:iam::123456789012:role/SecretsReader")
    print(secret.value)

**Session names** are auto-generated from the caller's module and function name
for CloudTrail auditing.  You can override this with the ``session_name`` parameter.


GitHub Runner Iteration
=======================

``GitHubActions.runners`` and ``GitHubActions.find_runners_by_label()`` return
**iterators**, not lists. They stream pages from the GitHub API lazily and yield
one ``GitHubActionsRunner`` at a time, so memory usage stays bounded to a
single page (~100 runners) regardless of organization size.

This matters in memory-constrained environments — for example, a 128 MB AWS
Lambda function running against a large organization would previously OOM
because ``runners`` materialized the entire list before returning. With the
iterator contract, ``find_runner_by_label()`` also short-circuits: once a match
is found on the current page, subsequent pages are never fetched.

Callers that need a materialized collection should wrap the result with
``list()``::

    all_runners = list(gha.runners)
    alphas = list(gha.find_runners_by_label("alpha"))

Typical lazy usage::

    for runner in gha.runners:
        if runner.busy:
            continue
        gha.deregister_runner(runner)

Deregistering while iterating is safe: ``deregister_runner`` issues an
independent ``DELETE /orgs/{org}/actions/runners/{id}`` request and does not
mutate the paginated list response that the iterator is currently reading
from. Contrast this with iterating a local list and mutating it in place,
which Python forbids — the GitHub pagination cursor lives server-side and
is advanced only when the iterator asks for the next page.


Caching Behaviour
=================

Several classes use ``cached_property_with_ttl`` to avoid redundant API calls.
The default TTL is **10 seconds** -- after that the property is re-fetched on
next access.

Properties that use TTL caching include:

- ``EC2Instance._describe_instance`` (instance metadata)
- ``GitHubActionsRunner._runner_data`` (runner status)

This means rapid successive reads (e.g. checking ``instance.state`` twice in a
tight loop) hit the cache, but reads separated by more than 10 seconds always
get fresh data.


Client Lifecycle
================

Resource classes create their boto3 clients lazily on first use and reuse
them for the lifetime of the object.  This means:

1. Constructing a class is cheap -- no API calls are made.
2. The first property access or method call creates the client.
3. Subsequent calls reuse the same client.

If you need to refresh credentials (e.g. after a long-running process),
create a new instance of the class.


AWSResource Base Class
======================

All AWS resource wrapper classes follow the contract defined by ``AWSResource``:

- ``exists`` property -- returns ``True`` if the resource currently exists.
- ``delete()`` method -- idempotent deletion (no error if already absent).
- ``delete()`` uses EAFP (try/except), not check-then-act, to avoid TOCTOU
  race conditions.