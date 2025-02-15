"""
Module for a Route53 zone
"""

import logging
from typing import List

from infrahouse_core.aws import get_client
from infrahouse_core.aws.route53.exceptions import IHRecordNotFound, IHZoneNotFound

LOG = logging.getLogger(__name__)


class Zone:
    """
    Zone represents a Route53 zone.
    The zone can be instantiated from either a zone identifier or name.
    Either of them must be not None. If both are not None, zone identifier is preferred.

    :param zone_id: Zone identifier.
    :type zone_id: str
    :param zone_name: Zone name.
    :type zone_name: str
    """

    def __init__(self, zone_id: str = None, zone_name: str = None):
        if zone_name is None and zone_id is None:
            raise RuntimeError("Either zone_id or zone_name must be passed. Both can't be None.")
        self._zone_id = zone_id
        self._zone_name = zone_name

    @property
    def zone_id(self):
        """Zone identifier. Find by name if not specified during instantiation."""
        if self._zone_id is None:
            response = self._client.list_hosted_zones_by_name(DNSName=self.zone_name, MaxItems="1")
            if len(response["HostedZones"]) < 1:
                raise IHZoneNotFound(f"Route53 zone {self.zone_name} doesn't exist")

            if response["HostedZones"][0]["Name"] == self.zone_name:
                self._zone_id = response["HostedZones"][0]["Id"].split("/")[2]
            else:
                raise IHZoneNotFound(f"Route53 zone {self.zone_name} doesn't exist")

        return self._zone_id

    @property
    def zone_name(self):
        """Zone name. Find from zone identifier if not specified during instantiation."""
        if self._zone_name is None:
            try:
                response = self._client.get_hosted_zone(Id=self.zone_id)
                return response["HostedZone"]["Name"]
            except self._client.exceptions.NoSuchHostedZone as err:
                raise IHZoneNotFound(f"Route53 zone with identifier {self.zone_id} doesn't exist") from err

        if not self._zone_name.endswith("."):
            self._zone_name = self._zone_name + "."

        return self._zone_name

    def add_record(self, hostname: str, ip_address: str, ttl: int = 300):
        """
        Add A record.
        If the hostname record already exists in the zone, the ip_address will be added.
        Otherwise, a new record is created.
        """
        try:
            ip_list = self.search_hostname(hostname)
            ip_list.append(ip_address)
            self._client.change_resource_record_sets(
                HostedZoneId=self.zone_id,
                ChangeBatch={
                    "Changes": [
                        {
                            "Action": "UPSERT",
                            "ResourceRecordSet": {
                                "Name": f"{hostname}.{self.zone_name}",
                                "Type": "A",
                                "TTL": ttl,
                                "ResourceRecords": [{"Value": ip} for ip in ip_list],
                            },
                        }
                    ]
                },
            )
        except IHRecordNotFound:
            self._client.change_resource_record_sets(
                HostedZoneId=self.zone_id,
                ChangeBatch={
                    "Changes": [
                        {
                            "Action": "CREATE",
                            "ResourceRecordSet": {
                                "Name": f"{hostname}.{self.zone_name}",
                                "Type": "A",
                                "TTL": ttl,
                                "ResourceRecords": [
                                    {"Value": ip_address},
                                ],
                            },
                        }
                    ]
                },
            )

    def delete_record(self, hostname: str, ip_address: str):
        """
        Delete an A record that matches hostname and ip_address.
        """
        try:
            ip_list = self.search_hostname(hostname)
            if ip_list == [ip_address]:
                # the last IP address in the record
                self._client.change_resource_record_sets(
                    HostedZoneId=self.zone_id,
                    ChangeBatch={
                        "Changes": [
                            {
                                "Action": "DELETE",
                                "ResourceRecordSet": {
                                    "Name": f"{hostname}.{self.zone_name}",
                                    "Type": "A",
                                    "TTL": self._get_record_ttl(hostname),
                                    "ResourceRecords": [{"Value": ip} for ip in ip_list],
                                },
                            }
                        ]
                    },
                )
            else:
                if ip_address in ip_list:
                    ip_list.remove(ip_address)
                    self._client.change_resource_record_sets(
                        HostedZoneId=self.zone_id,
                        ChangeBatch={
                            "Changes": [
                                {
                                    "Action": "UPSERT",
                                    "ResourceRecordSet": {
                                        "Name": f"{hostname}.{self.zone_name}",
                                        "Type": "A",
                                        "TTL": self._get_record_ttl(hostname),
                                        "ResourceRecords": [{"Value": ip} for ip in ip_list],
                                    },
                                }
                            ]
                        },
                    )
                else:
                    raise IHRecordNotFound

        except IHRecordNotFound:
            LOG.warning(
                "Could not find A record in zone %s(%s) with hostname %s and IP address %s.",
                self.zone_name,
                self.zone_id,
                hostname,
                ip_address,
            )

    def search_hostname(self, hostname) -> List[str]:
        """
        Given a hostname, search an A record in the zone.
        The hostname should be w/o the domain part. I.e. foo, not foo.infrahouse.com.

        Returns a list of IP addresses or raises IHRecordNotFound.

        :param hostname: Hostname
        :type hostname: str
        :return: List of IP addresses
        :rtype: list(str)
        :raise IHRecordNotFound: if the given hostname can't be found.
        """
        full_name = f"{hostname}.{self.zone_name}"
        response = self._client.list_resource_record_sets(
            HostedZoneId=self.zone_id, StartRecordName=full_name, StartRecordType="A", MaxItems="1"
        )
        if response["ResourceRecordSets"] and response["ResourceRecordSets"][0]["Name"] == full_name:
            return [i["Value"] for i in response["ResourceRecordSets"][0]["ResourceRecords"]]

        raise IHRecordNotFound(f"A record {full_name} not found")

    @property
    def _client(self):
        return get_client("route53")

    def _get_record_ttl(self, hostname):
        full_name = f"{hostname}.{self.zone_name}"
        response = self._client.list_resource_record_sets(
            HostedZoneId=self.zone_id, StartRecordName=full_name, StartRecordType="A", MaxItems="1"
        )
        if response["ResourceRecordSets"][0]["Name"] == full_name:
            return response["ResourceRecordSets"][0]["TTL"]

        raise IHRecordNotFound(f"A record {full_name} not found")
