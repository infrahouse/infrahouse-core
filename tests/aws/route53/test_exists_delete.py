"""Tests for Zone.exists and Zone.delete()."""

from unittest import mock

from infrahouse_core.aws.route53.exceptions import IHZoneNotFound
from infrahouse_core.aws.route53.zone import Zone


def test_exists_true():
    """exists returns True when the zone is found."""
    zone_id = "Z1234567890ABC"
    mock_client = mock.MagicMock()
    mock_client.get_hosted_zone.return_value = {"HostedZone": {"Id": f"/hostedzone/{zone_id}", "Name": "example.com."}}
    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_id=zone_id)
        assert zone.exists is True
        mock_client.get_hosted_zone.assert_called_once_with(Id=zone_id)


def test_exists_false_no_such_zone():
    """exists returns False when NoSuchHostedZone is raised."""
    zone_id = "Z1234567890ABC"
    mock_client = mock.MagicMock()
    mock_client.exceptions.NoSuchHostedZone = type("NoSuchHostedZone", (Exception,), {})
    mock_client.get_hosted_zone.side_effect = mock_client.exceptions.NoSuchHostedZone("not found")

    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_id=zone_id)
        assert zone.exists is False


def test_exists_false_zone_not_found_by_name():
    """exists returns False when zone lookup by name raises IHZoneNotFound."""
    mock_client = mock.MagicMock()
    mock_client.list_hosted_zones_by_name.return_value = {
        "HostedZones": [{"Id": "/hostedzone/ZOTHER", "Name": "other.com."}],
    }
    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_name="nonexistent.com")
        assert zone.exists is False


def test_delete():
    """delete() removes all non-NS/SOA records and deletes the zone."""
    zone_id = "Z1234567890ABC"
    mock_client = mock.MagicMock()
    mock_client.get_hosted_zone.return_value = {"HostedZone": {"Id": f"/hostedzone/{zone_id}", "Name": "example.com."}}

    paginator = mock.MagicMock()
    paginator.paginate.return_value = [
        {
            "ResourceRecordSets": [
                {"Name": "example.com.", "Type": "NS", "TTL": 300, "ResourceRecords": [{"Value": "ns1.example.com."}]},
                {"Name": "example.com.", "Type": "SOA", "TTL": 300, "ResourceRecords": [{"Value": "soa data"}]},
                {
                    "Name": "foo.example.com.",
                    "Type": "A",
                    "TTL": 300,
                    "ResourceRecords": [{"Value": "10.0.0.1"}],
                },
                {
                    "Name": "bar.example.com.",
                    "Type": "CNAME",
                    "TTL": 300,
                    "ResourceRecords": [{"Value": "baz.example.com."}],
                },
            ]
        }
    ]
    mock_client.get_paginator.return_value = paginator

    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_id=zone_id)
        zone.delete()

        # Should have deleted A and CNAME records, but not NS and SOA
        mock_client.change_resource_record_sets.assert_called_once()
        call_args = mock_client.change_resource_record_sets.call_args
        changes = call_args[1]["ChangeBatch"]["Changes"]
        assert len(changes) == 2
        assert all(c["Action"] == "DELETE" for c in changes)
        deleted_types = {c["ResourceRecordSet"]["Type"] for c in changes}
        assert deleted_types == {"A", "CNAME"}

        mock_client.delete_hosted_zone.assert_called_once_with(Id=zone_id)


def test_delete_not_exists():
    """delete() on a non-existent zone is a no-op."""
    mock_client = mock.MagicMock()
    mock_client.list_hosted_zones_by_name.return_value = {
        "HostedZones": [{"Id": "/hostedzone/ZOTHER", "Name": "other.com."}],
    }
    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_name="nonexistent.com")
        zone.delete()  # Should not raise
        mock_client.delete_hosted_zone.assert_not_called()


def test_delete_empty_zone():
    """delete() on a zone with only NS/SOA records still deletes the zone."""
    zone_id = "Z1234567890ABC"
    mock_client = mock.MagicMock()
    mock_client.get_hosted_zone.return_value = {"HostedZone": {"Id": f"/hostedzone/{zone_id}", "Name": "example.com."}}

    paginator = mock.MagicMock()
    paginator.paginate.return_value = [
        {
            "ResourceRecordSets": [
                {"Name": "example.com.", "Type": "NS", "TTL": 300, "ResourceRecords": [{"Value": "ns1.example.com."}]},
                {"Name": "example.com.", "Type": "SOA", "TTL": 300, "ResourceRecords": [{"Value": "soa data"}]},
            ]
        }
    ]
    mock_client.get_paginator.return_value = paginator

    with mock.patch.object(Zone, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        zone = Zone(zone_id=zone_id)
        zone.delete()

        # No change_resource_record_sets call (nothing to delete)
        mock_client.change_resource_record_sets.assert_not_called()
        # But zone itself is deleted
        mock_client.delete_hosted_zone.assert_called_once_with(Id=zone_id)
