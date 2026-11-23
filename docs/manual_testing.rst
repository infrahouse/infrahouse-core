=============================
Testing the SSO login by hand
=============================

The unit tests fake AWS. ``scripts/check_sso_login.py`` runs the real SSO login against your IAM Identity Center,
with the ``infrahouse_core`` of this checkout, the way ih-aws runs it, and then checks the result. Run it after a change
to :mod:`infrahouse_core.aws.sso_login` or :func:`infrahouse_core.aws.get_aws_session`, and before a release.


What it touches
===============

The script runs in a sandbox: a new private ``HOME`` in your temporary directory, with a copy of your AWS config. The
login, botocore and the AWS CLI keep their token cache there. So:

- your own ``~/.aws/sso/cache`` is neither read nor changed, and the ``aws`` sessions you have keep working;
- every run starts with no token, so every run asks you to approve a login;
- the sandbox, with the token in it, is deleted when the script ends, even after Ctrl-C. ``--keep-sandbox`` keeps it.

The script prints no secrets: only key names, file modes, expiry times and ARNs.


Before you start
================

You need:

- this checkout's development virtualenv (``make bootstrap``). The script refuses to run with an ``infrahouse_core``
  installed from anywhere else;
- two profiles in ``~/.aws/config`` that use the same ``sso-session``, for example:

  .. code-block:: ini

      [sso-session my-sso]
      sso_start_url = https://my-company.awsapps.com/start
      sso_region = us-west-2
      sso_registration_scopes = sso:account:access

      [profile dev]
      sso_session = my-sso
      sso_account_id = 111111111111
      sso_role_name = AdministratorAccess
      region = us-west-1

      [profile prod]
      sso_session = my-sso
      sso_account_id = 222222222222
      sso_role_name = AdministratorAccess
      region = us-west-1

- optionally, the AWS CLI v2 on your ``PATH``, to check that the CLI uses the same token.


Running it
==========

On a laptop the login uses the authorization code flow with PKCE. Your browser opens; approve the request, and there is
no code to enter:

.. code-block:: bash

    python scripts/check_sso_login.py dev prod

To use the device flow, as ``use_device_code=True`` does, run the following. The script prints a URL and a code; open
the URL on any device and enter the code. On a laptop the browser also opens the URL, with the code filled in:

.. code-block:: bash

    python scripts/check_sso_login.py --device-code dev prod

In an SSH session the device flow runs without the flag. To try that fallback on a laptop, run:

.. code-block:: bash

    SSH_TTY=1 python scripts/check_sso_login.py dev prod

The first profile logs in, and the others must connect with its token. If you give only one profile, the script adds
another profile of the same sso-session from your config, if it finds one.

The script prints one line per check, starting with ``PASS``, ``FAIL``, ``SKIP`` or ``INFO``, and a summary. The log of
the login, and the URL and code to approve it, go to stderr. A run where every check passes looks like this:

.. code-block:: text

    PASS  dev: get_aws_session() logged in
    INFO  Logging in with the authorization code flow (PKCE), in the browser on this machine. It took 9 s.
    PASS  dev: connected as arn:aws:sts::111111111111:assumed-role/AWSReservedSSO_AdministratorAccess_0123/me
    PASS  the token is in ~/.aws/sso/cache/0ad374308c5a4e22f723adf10145eafad7c4031c.json
    PASS  it is the only file there
    PASS  the token file is 0600
    PASS  ~/.aws/sso/cache is 0700
    PASS  ~/.aws/sso is 0700
    PASS  the token has startUrl, region, accessToken, expiresAt, clientId, clientSecret, registrationExpiresAt
    PASS  its startUrl and region are the sso-session's
    PASS  the token has a refreshToken, so botocore can refresh it
    PASS  expiresAt is 2026-11-23T15:40:53Z, in 0 h 59 min
    PASS  registrationExpiresAt is 2027-02-21T14:40:53Z, in 89 days
    PASS  prod: get_aws_session() connects with the same token, and no other login, as arn:aws:sts::222222222222:...
    PASS  aws sts get-caller-identity --profile prod uses the token, as arn:aws:sts::222222222222:...
    PASS  botocore refreshes a token that expires in 5 minutes
    PASS  the new access token expires later, at 2026-11-23T15:40:58Z
    PASS  the token file is still 0600
    INFO  The refreshed token has a refreshToken too.

    Every check passed.

The exit code is 0 when every check passed, 1 when one failed, and 2 when the checks couldn't start: for example, an
unknown profile, or profiles of different sso-sessions.

These options change what the script does:

``--region REGION``
    The region of the sessions. By default, each profile's region.
``--config PATH``
    The AWS config to copy into the sandbox. By default, ``$AWS_CONFIG_FILE``, then ``~/.aws/config``.
``--skip-aws-cli``
    Skip the AWS CLI check.
``--skip-refresh``
    Skip the refresh check.
``--keep-sandbox``
    Keep the sandbox for more checks by hand. The script prints how to run ``aws`` with it, and how to delete it.
    Delete it when you are done: it holds a live SSO token.


What it checks
==============

#. **The login.** ``get_aws_session()`` for the first profile finds no token, logs in, and connects to STS. The script
   reports which flow ran, and why. With ``--device-code``, or in an SSH session, it checks that the device flow ran.
#. **The token file.** It is ``~/.aws/sso/cache/<sha1 of the sso-session name>.json``, the file that botocore and
   ``aws sso login`` use, and the only file there. Its mode is 0600, and the mode of ``~/.aws/sso`` and
   ``~/.aws/sso/cache`` is 0700.
#. **The token.** It has every key botocore needs to use and refresh it, including a ``refreshToken``. ``expiresAt``
   and ``registrationExpiresAt`` are UTC times in botocore's format, and are in the future. The access token is
   short-lived: AWS issues it for about an hour. botocore renews it with the ``refreshToken`` when it is used in its
   last 15 minutes, for as long as the AWS access portal session lasts; after that, a new login is needed. The
   session length is set in IAM Identity Center (see `Configure AWS access portal session duration
   <https://docs.aws.amazon.com/singlesignon/latest/userguide/configure-user-session.html>`_). The client registration
   lasts about 90 days.
#. **The shared token.** ``get_aws_session()`` for each of the other profiles connects with the same token, and asks
   for no other login. ih-aws used to ask for an approval for every profile; this is the fix for
   `#141 <https://github.com/infrahouse/infrahouse-core/issues/141>`_.
#. **The AWS CLI.** ``aws sts get-caller-identity --profile <the last profile>``, run with the sandbox ``HOME``, finds
   the token without ``aws sso login``.
#. **The refresh.** The script sets ``expiresAt`` to 5 minutes from now and connects with a new boto3 session. botocore
   refreshes a token in its last 15 minutes, so it must use the ``refreshToken``: the script checks for a new access
   token, a later ``expiresAt``, and a file that is still 0600. This check is skipped when the token has no
   ``refreshToken``, because that check has already failed.


What it doesn't check
=====================

- **ih-aws itself.** The script calls the library functions that ih-aws calls, but not the ``ih-aws`` command from
  infrahouse-toolkit. To check a release, run ``ih-aws`` with two profiles of one sso-session.
- **The error paths.** A denied approval, the 10-minute timeout, stray requests to the callback server, and a callback
  port that can't be bound are covered by the unit tests in ``tests/aws/sso_login``, against a fake AWS.
