"""
Module for EC2Instance class - a class tha represents an EC2 instance.
"""

from logging import getLogger

from boto3 import Session
from cached_property import cached_property_with_ttl
from ec2_metadata import ec2_metadata

from infrahouse_core.aws import get_client

LOG = getLogger()


class EC2Instance:
    """
    EC2Instance represents an EC2 instance.

    :param instance_id: Instance id. If omitted, the local instance is read from metadata.
    :type instance_id: str
    """

    def __init__(self, instance_id: str = None, region: str = None, ec2_client: Session = None):
        self._instance_id = instance_id
        self._region = region
        self._ec2_client = ec2_client

    @property
    def availability_zone(self) -> str:
        """
        :return: Availability zone where this instance is hosted.
        """
        return ec2_metadata.availability_zone

    @property
    def ec2_client(self):
        """
        :return: Boto3 EC2 client
        """
        if self._ec2_client is None:
            self._ec2_client = get_client("ec2", region=self._region)
        return self._ec2_client

    @property
    def instance_id(self) -> str:
        """
        :return: The instance's instance_id. It's read from metadata
            if the class instance was created w/o specifying it.
        """
        if self._instance_id is None:
            self._instance_id = ec2_metadata.instance_id
        return self._instance_id

    @property
    def hostname(self):
        """
        :return: Instance's private hostname.
        """
        return self.private_dns_name.split(".")[0] if self.private_dns_name else None

    @property
    def private_dns_name(self):
        """
        :return: Instance's private DNS name.
        """
        return self._describe_instance["PrivateDnsName"]

    @property
    def private_ip(self):
        """
        :return: Instance's private IP address
        """
        return self._describe_instance["PrivateIpAddress"]

    @property
    def public_ip(self):
        """
        :return: Instance's public IP address
        """
        return self._describe_instance["PublicIpAddress"]

    @property
    def state(self) -> str:
        """
        :return: EC2 instance state e.g. ``Running``, ``Terminated``, etc.
        """
        return self._describe_instance["State"]["Name"]

    @property
    def tags(self) -> dict:
        """
        :return: A dictionary with the instance tags. Keys are tag names, and values - the tag values.
        """
        return {tag["Key"]: tag["Value"] for tag in self._describe_instance["Tags"]}

    def add_tag(self, key: str, value: str):
        """Add a tag to the instance."""
        self.ec2_client.create_tags(
            Resources=[
                self.instance_id,
            ],
            Tags=[
                {
                    "Key": key,
                    "Value": value,
                },
            ],
        )

    @cached_property_with_ttl(ttl=10)
    def _describe_instance(self):
        return self.ec2_client.describe_instances(
            InstanceIds=[
                self.instance_id,
            ],
        )[
            "Reservations"
        ][0][
            "Instances"
        ][0]
