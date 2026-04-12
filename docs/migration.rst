===============
Common Patterns
===============

This guide shows what infrahouse-core simplifies compared to raw boto3,
and documents deprecated constructor parameters.


From boto3 to infrahouse-core
=============================

infrahouse-core is a convenience layer on top of boto3, not a replacement.
boto3 is still the engine underneath -- infrahouse-core simplifies common
operations by providing sensible defaults, role assumption, and
property-based access to resource attributes.

**You don't need to stop using boto3.**  Use infrahouse-core where it saves
you boilerplate, and drop down to boto3 directly when you need full control.

EC2 instance metadata
---------------------

Before (boto3)::

    import boto3

    ec2 = boto3.client("ec2")
    response = ec2.describe_instances(InstanceIds=["i-abc123"])
    instance = response["Reservations"][0]["Instances"][0]
    state = instance["State"]["Name"]
    private_ip = instance.get("PrivateIpAddress")
    tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}

After (infrahouse-core)::

    from infrahouse_core.aws.ec2_instance import EC2Instance

    instance = EC2Instance("i-abc123", region="us-east-1")
    state = instance.state
    private_ip = instance.private_ip
    tags = instance.tags

Running commands via SSM
------------------------

Before (boto3)::

    import boto3
    from time import sleep

    ssm = boto3.client("ssm")
    response = ssm.send_command(
        InstanceIds=["i-abc123"],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["hostname"]},
    )
    command_id = response["Command"]["CommandId"]
    # ... poll for completion, handle retries, parse output ...

After (infrahouse-core)::

    instance = EC2Instance("i-abc123", region="us-east-1")
    exit_code, stdout, stderr = instance.execute_command("hostname")

Secrets Manager
---------------

Before (boto3)::

    import boto3

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId="my-secret")
    value = response["SecretString"]

After (infrahouse-core)::

    from infrahouse_core.aws.secretsmanager import Secret

    secret = Secret("my-secret", region="us-east-1")
    value = secret.value

The ``Secret`` class also provides ``ensure_present()`` and ``ensure_absent()``
for idempotent create/delete operations.

DynamoDB distributed locking
----------------------------

Before (boto3) -- manual conditional writes, retry loops, TTL management.

After (infrahouse-core)::

    from infrahouse_core.aws.dynamodb import DynamoDBTable

    table = DynamoDBTable("my-locks", region="us-east-1")
    with table.lock("deploy-service", timeout=60, ttl=600):
        run_deployment()

Cross-account access
--------------------

All resource classes accept ``role_arn`` for cross-account operations::

    secret = Secret("my-secret", role_arn="arn:aws:iam::123456789012:role/Reader")
    instance = EC2Instance("i-abc123", role_arn="arn:aws:iam::123456789012:role/Admin")


Breaking Changes
================

GitHubActions: ``runners`` / ``find_runners_by_label`` are now iterators
------------------------------------------------------------------------

**Changed in:** v1.0.0

``GitHubActions.runners`` and ``GitHubActions.find_runners_by_label()`` now
return ``Iterator[GitHubActionsRunner]`` instead of ``List[GitHubActionsRunner]``.
Pages are fetched from the GitHub API lazily as the iterator advances, keeping
memory usage bounded to a single API page. This fixes OOM crashes in 128 MB
AWS Lambda functions running against large organizations.

Code that iterated over the results keeps working unchanged::

    for runner in gha.runners:
        ...

    for runner in gha.find_runners_by_label("instance_id:i-abc123"):
        ...

Code that relied on list semantics must wrap with ``list()``:

Before::

    all_runners = gha.runners
    count = len(all_runners)
    first = all_runners[0]

    matches = gha.find_runners_by_label("alpha")
    if matches == []:
        ...

After::

    all_runners = list(gha.runners)
    count = len(all_runners)
    first = all_runners[0]

    matches = list(gha.find_runners_by_label("alpha"))
    if not matches:
        ...


Deprecated Parameters
=====================

EC2Instance: ``ec2_client`` and ``ssm_client``
-----------------------------------------------

**Deprecated in:** v0.20+

The ``ec2_client`` and ``ssm_client`` constructor parameters are deprecated.
Use ``role_arn`` instead -- the class creates its own clients internally.

Before (deprecated)::

    import boto3
    from infrahouse_core.aws.ec2_instance import EC2Instance

    ec2_client = boto3.client("ec2", region_name="us-east-1")
    ssm_client = boto3.client("ssm", region_name="us-east-1")
    instance = EC2Instance("i-abc123", ec2_client=ec2_client, ssm_client=ssm_client)

After::

    from infrahouse_core.aws.ec2_instance import EC2Instance

    instance = EC2Instance("i-abc123", region="us-east-1")

    # For cross-account access:
    instance = EC2Instance("i-abc123", role_arn="arn:aws:iam::123456789012:role/MyRole")