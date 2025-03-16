from unittest import mock

import pytest

from infrahouse_core.aws.route53.exceptions import IHRecordNotFound, IHZoneNotFound
from infrahouse_core.aws.route53.zone import Zone


def test_zone_name():
    zone = Zone(zone_name="ci-cd.infrahouse.com")
    assert zone.zone_name == "ci-cd.infrahouse.com."


def test_zone_id():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert zone.zone_id == "Z06790082OU0POPWOCPZ4"

    mock_client = mock.Mock()
    mock_client.list_hosted_zones_by_name.return_value = {
        "HostedZones": [
            {
                "Id": "/hostedzone/foo",
                "Name": "ci-cd.infrahouse.com.",
                "CallerReference": "terraform-20230810002609851800000001",
                "Config": {"Comment": "Managed by Terraform", "PrivateZone": False},
                "ResourceRecordSetCount": 5,
            }
        ],
        "DNSName": "ci-cd.infrahouse.com",
        "IsTruncated": False,
        "MaxItems": "1",
    }
    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_name="ci-cd.infrahouse.com")
        assert zone.zone_id == "foo"
        mock_client.list_hosted_zones_by_name.assert_called_once_with(DNSName="ci-cd.infrahouse.com.", MaxItems="1")


def test_zone_id_not_found():
    mock_client = mock.Mock()
    mock_client.list_hosted_zones_by_name.return_value = {
        "HostedZones": [
            {
                "Id": "/hostedzone/foo",
                "Name": "ci-cd.infrahouse.com.",
                "CallerReference": "terraform-20230810002609851800000001",
                "Config": {"Comment": "Managed by Terraform", "PrivateZone": False},
                "ResourceRecordSetCount": 5,
            }
        ],
        "DNSName": "ci-cd.infrahouse.com",
        "IsTruncated": False,
        "MaxItems": "1",
    }
    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_name="foo_zone")
        with pytest.raises(IHZoneNotFound):
            assert zone.zone_id == "foo"
        mock_client.list_hosted_zones_by_name.assert_called_once_with(DNSName="foo_zone.", MaxItems="1")


def test_zone_name_by_id():
    mock_client = mock.Mock()
    mock_client.get_hosted_zone.return_value = {
        "HostedZone": {
            "Id": "/hostedzone/foo",
            "Name": "ci-cd.infrahouse.com.",
            "CallerReference": "terraform-20230810002609851800000001",
            "Config": {"Comment": "Managed by Terraform", "PrivateZone": False},
            "ResourceRecordSetCount": 5,
        },
        "DelegationSet": {
            "NameServers": [
                "ns-261.awsdns-32.com",
                "ns-1795.awsdns-32.co.uk",
                "ns-776.awsdns-33.net",
                "ns-1311.awsdns-35.org",
            ]
        },
    }
    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_id="foo")
        assert zone.zone_name == "ci-cd.infrahouse.com."
        mock_client.get_hosted_zone.assert_called_once_with(Id="foo")


@pytest.mark.parametrize(
    "response, result",
    [
        (
            {
                "ResourceRecordSets": [
                    {
                        "Name": "ip-10-1-100-243.ci-cd.infrahouse.com.",
                        "Type": "A",
                        "TTL": 300,
                        "ResourceRecords": [{"Value": "10.1.100.243"}],
                    }
                ],
                "IsTruncated": True,
                "NextRecordName": "ip-10-1-101-82.ci-cd.infrahouse.com.",
                "NextRecordType": "A",
                "MaxItems": "1",
            },
            ["10.1.100.243"],
        ),
        (
            {
                "ResourceRecordSets": [
                    {
                        "Name": "ip-10-1-100-243.ci-cd.infrahouse.com.",
                        "Type": "A",
                        "TTL": 300,
                        "ResourceRecords": [{"Value": "10.1.100.243"}, {"Value": "10.1.1.1"}],
                    }
                ],
                "IsTruncated": True,
                "NextRecordName": "ip-10-1-101-82.ci-cd.infrahouse.com.",
                "NextRecordType": "A",
                "MaxItems": "1",
            },
            ["10.1.100.243", "10.1.1.1"],
        ),
    ],
)
def test_search_hostname(response, result):
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert zone.search_hostname("ip-10-1-100-243") == [
    #     "10.1.100.243"
    # ]
    # return
    mock_client = mock.Mock()
    mock_client.list_resource_record_sets.return_value = response
    with (
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
    ):
        zone = Zone(zone_name="ci-cd.infrahouse.com")
        assert zone.search_hostname("ip-10-1-100-243") == result
        mock_client.list_resource_record_sets.assert_called_once_with(
            HostedZoneId="foo_id",
            StartRecordName="ip-10-1-100-243.ci-cd.infrahouse.com.",
            StartRecordType="A",
            MaxItems="1",
        )


def test_search_hostname_not_found():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert zone.search_hostname("foo") == ["10.1.100.243"]
    mock_client = mock.Mock()
    mock_client.list_resource_record_sets.return_value = {
        "ResourceRecordSets": [
            {
                "Name": "ip-10-1-100-243.ci-cd.infrahouse.com.",
                "Type": "A",
                "TTL": 300,
                "ResourceRecords": [{"Value": "10.1.100.243"}],
            }
        ],
        "NextRecordName": "ip-10-1-101-82.ci-cd.infrahouse.com.",
        "NextRecordType": "A",
        "MaxItems": "1",
    }
    with (
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
    ):
        zone = Zone(zone_name="ci-cd.infrahouse.com")
        with pytest.raises(IHRecordNotFound):
            assert zone.search_hostname("foo")
        mock_client.list_resource_record_sets.assert_called_once_with(
            HostedZoneId="foo_id", StartRecordName="foo.ci-cd.infrahouse.com.", StartRecordType="A", MaxItems="1"
        )


def test_add_one_record():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # zone.add_record("foo", "10.1.1.1")
    # assert zone.search_hostname("foo") == ["10.1.1.1"]
    # zone.add_record("foo", "10.1.1.2")
    # assert zone.search_hostname("foo") == ["10.1.1.1", "10.1.1.2"]
    mock_client = mock.Mock()
    with (
        mock.patch.object(Zone, "search_hostname", side_effect=IHRecordNotFound),
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
    ):
        zone = Zone(zone_name="foo.com")
        zone.add_record("foo", "10.1.1.1")
        mock_client.change_resource_record_sets.assert_called_once_with(
            HostedZoneId="foo_id",
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "CREATE",
                        "ResourceRecordSet": {
                            "Name": "foo.foo.com.",
                            "Type": "A",
                            "TTL": 300,
                            "ResourceRecords": [{"Value": "10.1.1.1"}],
                        },
                    }
                ]
            },
        )


def test_add_second_record():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # zone.add_record("foo", "10.1.1.1")
    # assert zone.search_hostname("foo") == ["10.1.1.1"]
    # zone.add_record("foo", "10.1.1.2")
    # assert zone.search_hostname("foo") == ["10.1.1.1", "10.1.1.2"]
    mock_client = mock.Mock()
    with (
        mock.patch.object(Zone, "search_hostname", return_value=["10.1.1.1"]),
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
    ):
        zone = Zone(zone_name="foo.com")
        zone.add_record("foo", "10.1.1.2")
        mock_client.change_resource_record_sets.assert_called_once_with(
            HostedZoneId="foo_id",
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": "foo.foo.com.",
                            "Type": "A",
                            "TTL": 300,
                            "ResourceRecords": [{"Value": "10.1.1.1"}, {"Value": "10.1.1.2"}],
                        },
                    }
                ]
            },
        )


def test_delete_first_record():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert sorted(zone.search_hostname("foo")) == sorted(["10.1.1.1", "10.1.1.2"])
    # zone.delete_record("foo", "10.1.1.1")
    # assert zone.search_hostname("foo") == ["10.1.1.2"]
    # zone.delete_record("foo", "10.1.1.2")
    # with pytest.raises(IHRecordNotFound):
    #     assert zone.search_hostname("foo")
    mock_client = mock.Mock()
    with (
        mock.patch.object(Zone, "search_hostname", return_value=["10.1.1.1", "10.1.1.2"]),
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
        mock.patch.object(Zone, "_get_record_ttl", return_value=300),
    ):
        zone = Zone(zone_name="foo.com")
        zone.delete_record("foo", "10.1.1.1")
        mock_client.change_resource_record_sets.assert_called_once_with(
            HostedZoneId="foo_id",
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "UPSERT",
                        "ResourceRecordSet": {
                            "Name": "foo.foo.com.",
                            "Type": "A",
                            "TTL": 300,
                            "ResourceRecords": [{"Value": "10.1.1.2"}],
                        },
                    }
                ]
            },
        )


def test_delete_last_record():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert sorted(zone.search_hostname("foo")) == sorted(["10.1.1.1", "10.1.1.2"])
    # zone.delete_record("foo", "10.1.1.1")
    # assert zone.search_hostname("foo") == ["10.1.1.2"]
    # zone.delete_record("foo", "10.1.1.2")
    # with pytest.raises(IHRecordNotFound):
    #     assert zone.search_hostname("foo")
    mock_client = mock.Mock()
    with (
        mock.patch.object(Zone, "search_hostname", return_value=["10.1.1.1"]),
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
        mock.patch.object(Zone, "_get_record_ttl", return_value=300),
    ):
        zone = Zone(zone_name="foo.com")
        zone.delete_record("foo", "10.1.1.1")
        mock_client.change_resource_record_sets.assert_called_once_with(
            HostedZoneId="foo_id",
            ChangeBatch={
                "Changes": [
                    {
                        "Action": "DELETE",
                        "ResourceRecordSet": {
                            "Name": "foo.foo.com.",
                            "Type": "A",
                            "TTL": 300,
                            "ResourceRecords": [{"Value": "10.1.1.1"}],
                        },
                    }
                ]
            },
        )


def test_delete_non_existing_record():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert sorted(zone.search_hostname("foo")) == sorted(["10.1.1.1", "10.1.1.2"])
    # zone.delete_record("foo", "10.1.1.1")
    # assert zone.search_hostname("foo") == ["10.1.1.2"]
    # zone.delete_record("foo", "10.1.1.2")
    # with pytest.raises(IHRecordNotFound):
    #     assert zone.search_hostname("foo")
    mock_client = mock.Mock()
    with (
        mock.patch.object(Zone, "search_hostname", return_value=["10.1.1.1"]),
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
        mock.patch.object(Zone, "_get_record_ttl", return_value=300),
    ):
        zone = Zone(zone_name="foo.com")
        zone.delete_record("foo", "10.1.1.2")
        mock_client.change_resource_record_sets.assert_not_called()


def test_search_hostname_new():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert zone.search_hostname("ip-10-1-102-189") == ["10.1.100.243"]
    mock_response = {"ResourceRecordSets": [], "IsTruncated": False, "MaxItems": "1"}
    mock_client = mock.Mock()
    mock_client.list_resource_record_sets.return_value = mock_response
    with (
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "zone_id", new_callable=mock.PropertyMock, return_value="foo_id"),
    ):
        zone = Zone(zone_name="foo.com")
        with pytest.raises(IHRecordNotFound):
            zone.search_hostname("ip-10-1-102-189")


def test_delete_record_unknown():
    # zone = Zone(zone_name="ci-cd.infrahouse.com")
    # assert zone.search_hostname("ip-10-1-102-189") == ["10.1.100.243"]
    mock_client = mock.Mock()

    with (
        mock.patch.object(Zone, "search_hostname", side_effect=IHRecordNotFound) as mock_search_hostname,
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client),
        mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client) as mc,
    ):
        zone = Zone(zone_name="foo.com", zone_id="foo_id")
        zone.delete_record("ip-10-1-102-189", "10.1.102.189")
        mock_search_hostname.assert_called_once_with("ip-10-1-102-189")
        mc.change_resource_record_sets.assert_not_called()
