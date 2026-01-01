===============
InfraHouse Core
===============


.. image:: https://img.shields.io/pypi/v/infrahouse_core.svg
        :target: https://pypi.python.org/pypi/infrahouse_core

.. image:: https://readthedocs.org/projects/infrahouse-core/badge/?version=latest
        :target: https://infrahouse-core.readthedocs.io/en/latest/?version=latest
        :alt: Documentation Status




Lightweight Python library with AWS and other general purpose classes.


* Free software: Apache Software License 2.0
* Documentation: https://infrahouse-core.readthedocs.io.


Installation
------------

.. code-block:: bash

    pip install infrahouse-core


Features
--------

AWS Classes
~~~~~~~~~~~

* **EC2Instance** - Manage EC2 instances with SSM command execution support
* **ASG** - AutoScaling Group lifecycle management (instance refresh, lifecycle hooks)
* **DynamoDBTable** - DynamoDB operations with distributed locking support
* **Route53 Zone** - DNS record management (add/delete A records)
* **AWS Session Management** - SSO login, role assumption, credential handling

GitHub Integration
~~~~~~~~~~~~~~~~~~

* **GitHubActions** - Manage self-hosted GitHub Actions runners
* **GitHubActionsRunner** - Query runner status, labels, and metadata
* Token generation from GitHub App credentials stored in AWS Secrets Manager


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


Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
