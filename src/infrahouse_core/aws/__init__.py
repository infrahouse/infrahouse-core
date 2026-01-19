"""
AWS classes.
"""

import hashlib
import inspect
import json
import sys
import time
import webbrowser
from logging import getLogger
from os import environ, makedirs
from os import path as osp
from pprint import pformat
from time import sleep

import boto3
import requests
from boto3 import Session
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    SSOTokenLoadError,
    TokenRetrievalError,
)
from diskcache import Cache

from infrahouse_core.aws.config import AWSConfig
from infrahouse_core.aws.exceptions import IHAWSException
from infrahouse_core.fs import ensure_permissions

VALUE_MAP = {
    "AWS_ACCESS_KEY_ID": "AccessKeyId",
    "AWS_SECRET_ACCESS_KEY": "SecretAccessKey",
    "AWS_SESSION_TOKEN": "SessionToken",
    # These are old s3.fs options
    # Soon they will be deprecated
    # https://github.com/s3fs-fuse/s3fs-fuse/pull/1729
    "AWSACCESSKEYID": "AccessKeyId",
    "AWSSECRETACCESSKEY": "SecretAccessKey",
    "AWSSESSIONTOKEN": "SessionToken",
}

LOG = getLogger(__name__)


def assume_role(role_arn, region=None, session_name=None) -> dict:
    """
    Assume a given role and return a dictionary with credentials.

    :param role_arn: Role to be assumed.
    :type role_arn: str
    :param region: AWS region name.
    :type region: str
    :param session_name: Session name for the assumed role. If None, auto-generated from caller context.
    :type session_name: str
    :return: A dictionary with three keys: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN
    :rtype: dict
    """
    if session_name is None:
        # Auto-generate from caller context
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        caller = frame.function
        mod_name = module.__name__ if module else "infrahouse_core"
        session_name = f"{mod_name}.{caller}"

    try:
        LOG.debug("Assuming role %s with session name %s", role_arn, session_name)
        client = boto3.client("sts", region_name=region)
        response = client.assume_role(RoleArn=role_arn, RoleSessionName=session_name)
        # AccessKeyId is not secret, log it for debugging
        access_key_id = response["Credentials"]["AccessKeyId"]
        LOG.debug("Successfully assumed role %s (AccessKeyId: %s)", role_arn, access_key_id)
        return {var: response["Credentials"].get(key) for var, key in VALUE_MAP.items()}
    except ClientError as err:
        LOG.error(err)
        LOG.debug(
            "To revert environment:\n%s",
            "\n".join([f"unset {key}" for key in VALUE_MAP]),
        )
        raise


def get_aws_client(service_name: str, profile: str, region: str, session=None):
    """
    Get a client instance for an AWS service.

    :param service_name: AWS service e.g. ``ec2``.
    :param profile: AWS profile for authentication.
    :param region: AWS region.
    :param session: if an AWS session is passed, use it to create a client.
    :type session: Session
    :return: A client instance.
    """
    session = session or Session(region_name=region, profile_name=profile)
    # boto3 stubs use Literal types for service names; str works fine at runtime
    return session.client(service_name)  # type: ignore[arg-type]


def get_aws_session(aws_config: AWSConfig, aws_profile: str, aws_region: str) -> Session:
    """

    :param aws_config:
    :param aws_profile:
    :param aws_region:
    :return: Authenticated AWS session, or None if boto3 can connect to AWS without extra steps.
    """
    if aws_profile is None and "default" in aws_config.profiles:
        aws_profile = "default"

    try:
        response = get_aws_client("sts", aws_profile, aws_region).get_caller_identity()
        LOG.info("Connected to AWS as %s", response["Arn"])

    except (SSOTokenLoadError, TokenRetrievalError) as err:
        if not aws_profile:
            LOG.error("Try to run ih-aws with --aws-profile option.")
            LOG.error("Available profiles:\n\t%s", "\n\t".join(aws_config.profiles))
            sys.exit(1)
        LOG.debug(err)
        aws_session = aws_sso_login(aws_config, aws_profile, region=aws_region)
        response = get_aws_client("sts", aws_profile, aws_region, session=aws_session).get_caller_identity()
        LOG.info("Connected to AWS as %s", response["Arn"])
        return aws_session

    except NoCredentialsError as err:
        LOG.error(err)
        LOG.info("Try to run ih-aws with --aws-profile option.")
        LOG.info("Available profiles:\n\t%s", "\n\t".join(aws_config.profiles))
        sys.exit(1)

    return boto3.Session(region_name=aws_region)


def get_session(role_arn=None, region=None, session_name=None):
    """
    Get a boto3 session, optionally with assumed role credentials.

    Use this function when you need to create multiple clients or resources
    with the same credentials. For single client/resource creation, prefer
    :func:`get_client` or :func:`get_resource` instead.

    :param role_arn: IAM role ARN to assume. If None, returns a default session.
    :type role_arn: str
    :param region: AWS region name.
    :type region: str
    :param session_name: Session name for CloudTrail auditing. If None, auto-generated
        from caller context (module.function format).
    :type session_name: str
    :return: A boto3 Session object.
    :rtype: boto3.Session

    Example::

        # With role assumption
        session = get_session(role_arn="arn:aws:iam::123456789012:role/MyRole")
        ec2 = session.client("ec2")
        s3 = session.resource("s3")

        # Without role assumption (uses default credentials)
        session = get_session(region="us-west-2")
    """
    if role_arn:
        if session_name is None:
            # Auto-generate from caller context for CloudTrail auditing
            frame = inspect.stack()[1]
            module = inspect.getmodule(frame[0])
            caller = frame.function
            mod_name = module.__name__ if module else "unknown_module"
            session_name = f"{mod_name}.{caller}"

        sts = boto3.client("sts", region_name=region)
        assumed_role = sts.assume_role(RoleArn=role_arn, RoleSessionName=session_name)
        session = boto3.Session(
            aws_access_key_id=assumed_role["Credentials"]["AccessKeyId"],
            aws_secret_access_key=assumed_role["Credentials"]["SecretAccessKey"],
            aws_session_token=assumed_role["Credentials"]["SessionToken"],
            region_name=region,
        )
        # Verify the assumed identity
        sts = session.client("sts", region_name=region)
        response = sts.get_caller_identity()
        LOG.debug("Assumed role: %s", json.dumps(response, indent=4))
        return session

    return boto3.Session(region_name=region)


def get_client(service_name, role_arn=None, region=None, session_name=None):
    """
    Get an AWS service client, optionally assuming a role.

    This is a convenience wrapper around :func:`get_session` for creating
    a single boto3 client.

    :param service_name: AWS service name (e.g., "ec2", "s3", "dynamodb").
    :type service_name: str
    :param role_arn: IAM role ARN to assume. If None, uses default credentials.
    :type role_arn: str
    :param region: AWS region name.
    :type region: str
    :param session_name: Session name for CloudTrail auditing. If None, auto-generated.
    :type session_name: str
    :return: A boto3 client for the specified service.

    Example::

        # Cross-account access
        ec2 = get_client("ec2", role_arn="arn:aws:iam::123456789012:role/MyRole")

        # Same account, specific region
        s3 = get_client("s3", region="eu-west-1")
    """
    session = get_session(role_arn=role_arn, region=region, session_name=session_name)
    LOG.debug("Returning %s client in %s region", service_name, session.region_name)
    # boto3 stubs use Literal types for service names; str works fine at runtime
    return session.client(service_name, region_name=region)  # type: ignore[arg-type]


def get_resource(service_name, role_arn=None, region=None, session_name=None):
    """
    Get an AWS service resource, optionally assuming a role.

    This is a convenience wrapper around :func:`get_session` for creating
    a single boto3 resource. Use this for high-level AWS interfaces like
    DynamoDB Table or S3 Bucket objects.

    :param service_name: AWS service name (e.g., "dynamodb", "s3").
    :type service_name: str
    :param role_arn: IAM role ARN to assume. If None, uses default credentials.
    :type role_arn: str
    :param region: AWS region name.
    :type region: str
    :param session_name: Session name for CloudTrail auditing. If None, auto-generated.
    :type session_name: str
    :return: A boto3 resource for the specified service.

    Example::

        # DynamoDB with cross-account access
        dynamodb = get_resource("dynamodb", role_arn="arn:aws:iam::123456789012:role/MyRole")
        table = dynamodb.Table("my-table")

        # S3 in specific region
        s3 = get_resource("s3", region="us-east-1")
        bucket = s3.Bucket("my-bucket")
    """
    session = get_session(role_arn=role_arn, region=region, session_name=session_name)
    LOG.debug("Returning %s resource in %s region", service_name, session.region_name)
    # boto3 stubs use Literal types for service names; str works fine at runtime
    return session.resource(service_name, region_name=region)  # type: ignore[arg-type]


def get_credentials_from_profile() -> dict:
    """
    Another way to get AWS credentials is from EC2 instance metadata.

    :return: A dictionary with AWS_* variables.
    """
    LOG.debug("Using AWS credentials from instance metadata")
    url = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
    profile_name = requests.get(url, timeout=10).text
    LOG.debug("Profile name %s", profile_name)
    profile_data = requests.get(f"{url}/{profile_name}", timeout=10).json()
    profile_data["SessionToken"] = profile_data["Token"]

    return {var: profile_data.get(key) for var, key in VALUE_MAP.items()}


def get_credentials_from_environ():
    """Yet another way to get credentials.

    If environment is already configured for AWS access, simply get the credential from the environment.
    This is a situation when a user configures AWS_* in their env.
    Or when a role has been assumed and AWS_* are configured.

    :return: A dictionary with AWS_* variables.
    """
    LOG.debug("Using AWS credentials from environment")
    return {
        "AWS_ACCESS_KEY_ID": environ.get("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWS_SESSION_TOKEN": environ.get("AWS_SESSION_TOKEN"),
        "AWSACCESSKEYID": environ.get("AWS_ACCESS_KEY_ID"),
        "AWSSECRETACCESSKEY": environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWSSESSIONTOKEN": environ.get("AWS_SESSION_TOKEN"),
    }


def get_secret(secretsmanager_client, secret_name):
    """
    Retrieve a value of a secret by its name.
    """
    response = secretsmanager_client.get_secret_value(
        SecretId=secret_name,
    )
    # Log hash of secret value for verification without exposing the actual secret
    secret_value = response["SecretString"]
    secret_hash = hashlib.sha256(secret_value.encode()).hexdigest()[:16]
    LOG.debug("Successfully retrieved secret '%s' (value hash: %s)", secret_name, secret_hash)
    return secret_value


def aws_sso_login(aws_config: AWSConfig, profile_name: str, region: str = None):
    """
    Login into AWS using SSO.

    Credit:
    https://stackoverflow.com/questions/62311866/how-to-use-the-aws-python-sdk-while-connecting-via-sso-credentials
    """
    cache_directory = osp.expanduser("~/.infrahouse-toolkit")

    # Ensure directory exists with secure permissions BEFORE use to prevent race condition
    # where credentials could be exposed with default permissions
    makedirs(cache_directory, mode=0o700, exist_ok=True)
    ensure_permissions(cache_directory, 0o700)

    with Cache(directory=cache_directory) as cache_reference:
        cache_key = f"ih-ec2-credentials-{profile_name}"
        credentials = cache_reference.get(cache_key)
        if not credentials:
            credentials = _get_credentials(aws_config, profile_name)
            cache_reference.set(
                cache_key,
                credentials,
                expire=int(int(credentials["expiration"]) / 1000 - int(time.time())),
            )

    return Session(
        region_name=region or aws_config.get_region(profile_name),
        aws_access_key_id=credentials["accessKeyId"],
        aws_secret_access_key=credentials["secretAccessKey"],
        aws_session_token=credentials["sessionToken"],
    )


def _format_client_error(err: ClientError) -> str:
    """Extract error code and message from a ClientError."""
    error_info = err.response.get("Error", {})
    code = error_info.get("Code", "Unknown")
    message = error_info.get("Message", "No details provided")
    return f"{code} - {message}"


def _get_credentials(aws_config: AWSConfig, profile_name: str):
    """
    Login into AWS using SSO.

    Credit:
    https://stackoverflow.com/questions/62311866/how-to-use-the-aws-python-sdk-while-connecting-via-sso-credentials

    :raise IHAWSException: If user didn't confirm auth or SSO configuration is invalid.
    """

    session = Session()
    sso_oidc = session.client("sso-oidc")

    try:
        client_creds = sso_oidc.register_client(
            clientName="infrahouse-toolkit",
            clientType="public",
        )
    except ClientError as err:
        raise IHAWSException(
            f"Failed to register SSO client for profile '{profile_name}': {_format_client_error(err)}"
        ) from err

    LOG.debug("client_creds = %s", pformat(client_creds, indent=4))

    start_url = aws_config.get_start_url(profile_name)
    LOG.debug("Using SSO start URL: %s", start_url)

    try:
        device_authorization = sso_oidc.start_device_authorization(
            clientId=client_creds["clientId"],
            clientSecret=client_creds["clientSecret"],
            startUrl=start_url,
        )
    except ClientError as err:
        raise IHAWSException(
            f"Failed to start SSO device authorization for profile '{profile_name}': "
            f"{_format_client_error(err)}. "
            f"Check your SSO configuration (sso_start_url: {start_url})"
        ) from err

    LOG.debug("device_authorization = %s", pformat(device_authorization, indent=4))
    device_code = device_authorization["deviceCode"]
    expires_in = device_authorization["expiresIn"]
    interval = device_authorization["interval"]
    LOG.info("Verify user code: %s", device_authorization["userCode"])
    webbrowser.open(device_authorization["verificationUriComplete"], autoraise=True)
    for _ in range(1, expires_in // interval + 1):
        sleep(interval)
        try:
            token = sso_oidc.create_token(
                grantType="urn:ietf:params:oauth:grant-type:device_code",
                deviceCode=device_code,
                clientId=client_creds["clientId"],
                clientSecret=client_creds["clientSecret"],
            )
            return session.client("sso").get_role_credentials(
                roleName=aws_config.get_role(profile_name),
                accountId=aws_config.get_account_id(profile_name),
                accessToken=token["accessToken"],
            )["roleCredentials"]
        except sso_oidc.exceptions.AuthorizationPendingException:
            pass

    raise IHAWSException(f"The verification code isn't confirmed by user in {expires_in} seconds")
