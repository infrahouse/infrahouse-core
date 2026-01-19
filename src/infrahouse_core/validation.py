"""Input validation utilities for AWS resource identifiers."""

import re
from logging import getLogger
from typing import Optional

LOG = getLogger(__name__)


def validate_instance_id(instance_id: Optional[str]) -> None:
    """
    Validate EC2 instance ID format.

    :param instance_id: Instance ID to validate
    :type instance_id: str or None
    :raises ValueError: If instance_id is invalid
    """
    if not instance_id:
        return  # None or empty string is valid - will be read from metadata

    if not isinstance(instance_id, str):
        raise ValueError(f"instance_id must be a string, got {type(instance_id).__name__}")

    if not re.match(r"^i-[0-9a-f]{8,17}$", instance_id):
        raise ValueError(f"Invalid instance ID format: '{instance_id}'. " f"Expected format: i-xxxxxxxxxxxxxxxxx")


def validate_role_arn(role_arn: Optional[str]) -> None:
    """
    Validate IAM role ARN format.

    :param role_arn: Role ARN to validate
    :type role_arn: str or None
    :raises ValueError: If role_arn is invalid
    """
    if not role_arn:
        return  # None or empty string is valid - no role assumption

    if not isinstance(role_arn, str):
        raise ValueError(f"role_arn must be a string, got {type(role_arn).__name__}")

    # AWS ARN format: arn:partition:service:region:account-id:resource
    # For IAM roles: arn:aws:iam::123456789012:role/RoleName
    # Also support arn:aws-us-gov:iam:: for GovCloud
    if not re.match(r"^arn:aws(-[a-z-]+)?:iam::\d{12}:role/.+$", role_arn):
        raise ValueError(
            f"Invalid role ARN format: '{role_arn}'. " f"Expected format: arn:aws:iam::123456789012:role/RoleName"
        )


def validate_region(region: Optional[str]) -> None:
    """
    Validate AWS region name format.

    :param region: AWS region name to validate
    :type region: str or None
    :raises ValueError: If region is invalid
    """
    if region is None:
        return  # None is valid - will use default resolution

    if not isinstance(region, str):
        raise ValueError(f"region must be a string, got {type(region).__name__}")

    # AWS region format: us-east-1, eu-west-2, ap-southeast-1, us-gov-west-1, etc.
    if not re.match(r"^[a-z]{2}(-[a-z]+)+-\d{1}$", region):
        raise ValueError(f"Invalid region format: '{region}'. " f"Expected format: us-east-1, eu-west-2, etc.")


def validate_dns_name(dns_name: Optional[str]) -> None:
    """
    Validate DNS zone name format.

    :param dns_name: DNS name to validate
    :type dns_name: str or None
    :raises ValueError: If dns_name is invalid
    """
    if dns_name is None:
        return

    if not isinstance(dns_name, str):
        raise ValueError(f"dns_name must be a string, got {type(dns_name).__name__}")

    # Basic DNS name validation
    if not dns_name or len(dns_name) > 255:
        raise ValueError(f"Invalid DNS name length: '{dns_name}'")

    # Allow trailing dot
    name = dns_name.rstrip(".")

    # Check labels
    labels = name.split(".")
    if not labels:
        raise ValueError(f"Invalid DNS name: '{dns_name}'")

    for label in labels:
        if not label or len(label) > 63:
            raise ValueError(f"Invalid DNS label in '{dns_name}': '{label}'")
        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", label, re.IGNORECASE):
            raise ValueError(f"Invalid DNS label in '{dns_name}': '{label}'")


def validate_zone_id(zone_id: Optional[str]) -> None:
    """
    Validate Route53 hosted zone ID format.

    :param zone_id: Zone ID to validate
    :type zone_id: str or None
    :raises ValueError: If zone_id is invalid
    """
    if zone_id is None:
        return

    if not isinstance(zone_id, str):
        raise ValueError(f"zone_id must be a string, got {type(zone_id).__name__}")

    # Zone IDs are alphanumeric, may have /hostedzone/ prefix
    zone_id_clean = zone_id.replace("/hostedzone/", "")
    if not re.match(r"^[A-Z0-9]{1,32}$", zone_id_clean):
        raise ValueError(
            f"Invalid zone ID format: '{zone_id}'. " f"Expected alphanumeric string (e.g., Z1234567890ABC)"
        )
