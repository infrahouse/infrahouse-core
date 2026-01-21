===============
InfraHouse Core
===============

.. image:: https://img.shields.io/badge/Need%20Help%3F-Contact%20Us-0066CC
   :target: https://infrahouse.com/contact
   :alt: Need Help? Contact Us

.. image:: https://img.shields.io/pypi/v/infrahouse_core.svg
   :target: https://pypi.python.org/pypi/infrahouse_core
   :alt: PyPI Version

.. image:: https://readthedocs.org/projects/infrahouse-core/badge/?version=latest
   :target: https://infrahouse-core.readthedocs.io/en/latest/?version=latest
   :alt: Documentation Status

.. image:: https://img.shields.io/github/release/infrahouse/infrahouse-core.svg
   :target: https://github.com/infrahouse/infrahouse-core/releases/latest
   :alt: Latest Release

.. image:: https://img.shields.io/badge/AWS-EC2%20%7C%20DynamoDB%20%7C%20Route53%20%7C%20SSM-orange?logo=amazonaws
   :target: https://aws.amazon.com/
   :alt: AWS Services

.. image:: https://img.shields.io/pypi/pyversions/infrahouse-core
   :target: https://pypi.python.org/pypi/infrahouse_core
   :alt: Python Versions

.. image:: https://img.shields.io/badge/License-Apache_2.0-blue.svg
   :target: https://github.com/infrahouse/infrahouse-core/blob/main/LICENSE
   :alt: License

Lightweight Python library with AWS and other general purpose classes.


* Free software: Apache Software License 2.0
* Documentation: https://infrahouse-core.readthedocs.io.


Requirements
------------

* Python 3.10+
* Linux or macOS (Windows is not supported)

Installation
------------

.. code-block:: bash

    pip install infrahouse-core


Features
--------

AWS Classes
~~~~~~~~~~~

* **EC2Instance** - Manage EC2 instances with SSM command execution support
* **ASGInstance** - EC2 instance within an AutoScaling Group (lifecycle state, protection, health)
* **ASG** - AutoScaling Group lifecycle management (instance refresh, lifecycle hooks)
* **DynamoDBTable** - DynamoDB operations with distributed locking support
* **Route53 Zone** - DNS record management (add/delete A records)
* **Secret** - AWS Secrets Manager operations (create, read, update, delete)
* **AWS Session Management** - SSO login, role assumption, credential handling via
  ``get_session()``, ``get_client()``, ``get_resource()`` helpers

GitHub Integration
~~~~~~~~~~~~~~~~~~

* **GitHubActions** - Manage self-hosted GitHub Actions runners
* **GitHubActionsRunner** - Query runner status, labels, and metadata
* Token generation from GitHub App credentials stored in AWS Secrets Manager

Utilities
~~~~~~~~~

* **Input Validation** - Validators for AWS resource identifiers (instance IDs, ARNs, regions, DNS names)
* **Timeout** - Context manager for enforcing execution time limits (POSIX only)
* **Filesystem** - Secure permission management (``ensure_permissions()``)
* **Logging** - Configurable logging setup with stdout/stderr separation


Usage Examples
--------------

EC2 Instance with SSM Command Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from infrahouse_core.aws.ec2_instance import EC2Instance

    # Connect to an instance (optionally assume a role for cross-account access)
    instance = EC2Instance(
        instance_id="i-0123456789abcdef0",
        region="us-east-1",
        role_arn="arn:aws:iam::123456789012:role/MyRole"  # optional
    )

    # Execute a command via SSM
    exit_code, stdout, stderr = instance.execute_command("hostname")

    # Access instance properties
    print(instance.private_ip)
    print(instance.hostname)
    print(instance.tags)

DynamoDB Distributed Lock
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from infrahouse_core.aws.dynamodb import DynamoDBTable

    table = DynamoDBTable("my-lock-table", region="us-east-1")

    with table.lock("my-resource", timeout=30):
        # Critical section - only one process can hold this lock
        do_exclusive_work()

Route53 DNS Management
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from infrahouse_core.aws.route53.zone import Zone

    zone = Zone(zone_name="example.com")

    # Add an A record
    zone.add_record("myhost", "10.0.0.1", ttl=300)

    # Delete an A record
    zone.delete_record("myhost", "10.0.0.1")

Secrets Manager
~~~~~~~~~~~~~~~

.. code-block:: python

    from infrahouse_core.aws.secretsmanager import Secret

    # Read a secret
    secret = Secret("my-app/api-key", region="us-east-1")
    print(secret.value)  # Returns dict if JSON, else string

    # Create or update a secret
    secret.ensure_present({"username": "admin", "password": "secret123"})

    # Cross-account access
    secret = Secret(
        "prod/database-creds",
        role_arn="arn:aws:iam::123456789012:role/SecretsReader"
    )

Cross-Account AWS Access
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from infrahouse_core.aws import get_client, get_session

    # Get a client with assumed role
    ec2 = get_client(
        "ec2",
        role_arn="arn:aws:iam::123456789012:role/CrossAccountRole",
        region="us-west-2"
    )

    # Or get a session for multiple clients
    session = get_session(role_arn="arn:aws:iam::123456789012:role/MyRole")
    ec2 = session.client("ec2")
    s3 = session.client("s3")

GitHub Actions Runner Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from infrahouse_core.github import GitHubActions, GitHubAuth

    github = GitHubAuth(token="ghp_...", org="my-org")
    actions = GitHubActions(github)

    # List all runners
    for runner in actions.runners:
        print(f"{runner.name}: {runner.status}")

    # Find runners by label
    runners = actions.find_runners_by_label("self-hosted")


Contributing
------------

Contributions are welcome! Please see `CONTRIBUTING.rst`_ for guidelines.

.. _CONTRIBUTING.rst: https://github.com/infrahouse/infrahouse-core/blob/main/CONTRIBUTING.rst


License
-------

Apache Software License 2.0. See `LICENSE`_ for details.

.. _LICENSE: https://github.com/infrahouse/infrahouse-core/blob/main/LICENSE


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
