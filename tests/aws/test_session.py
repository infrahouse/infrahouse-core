"""Tests for the ``session`` parameter across resource classes.

When a pre-configured ``boto3.Session`` is supplied, every resource class
should create its boto3 client(s) from that session rather than via
:func:`get_client`.  When ``session`` is *not* supplied the behaviour
should remain unchanged (backward-compatible).
"""

# pylint: disable=protected-access

from unittest import mock

from infrahouse_core.aws.asg import ASG
from infrahouse_core.aws.asg_instance import ASGInstance
from infrahouse_core.aws.base import AWSResource
from infrahouse_core.aws.dynamodb import DynamoDBTable
from infrahouse_core.aws.ec2_instance import EC2Instance
from infrahouse_core.aws.route53.zone import Zone
from infrahouse_core.aws.s3_bucket import S3Bucket
from infrahouse_core.aws.secretsmanager import Secret

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ConcreteResource(AWSResource):
    """Minimal concrete subclass used for testing the base class."""

    @property
    def exists(self) -> bool:
        return True

    def delete(self) -> None:
        pass


# ---------------------------------------------------------------------------
# AWSResource base class
# ---------------------------------------------------------------------------


class TestAWSResourceSession:
    """Session parameter on the AWSResource base class."""

    def test_session_is_stored(self):
        """The session object is stored on the instance."""
        mock_session = mock.MagicMock()
        resource = _ConcreteResource("res-1", "ec2", session=mock_session)
        assert resource._session is mock_session

    def test_session_none_by_default(self):
        """session defaults to None when not provided."""
        resource = _ConcreteResource("res-1", "ec2", region="us-east-1")
        assert resource._session is None

    @mock.patch("infrahouse_core.aws.base.get_client")
    def test_client_uses_session_when_provided(self, mock_get_client):
        """_client creates the client from the session, not get_client."""
        mock_session = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_session.client.return_value = mock_client

        resource = _ConcreteResource("res-1", "ec2", region="us-west-2", session=mock_session)
        client = resource._client

        mock_session.client.assert_called_once_with("ec2", region_name="us-west-2")
        mock_get_client.assert_not_called()
        assert client is mock_client

    @mock.patch("infrahouse_core.aws.base.get_client")
    def test_client_uses_get_client_without_session(self, mock_get_client):
        """_client falls back to get_client when no session is provided."""
        mock_client = mock.MagicMock()
        mock_get_client.return_value = mock_client

        resource = _ConcreteResource("res-1", "ec2", region="us-east-1", role_arn="arn:aws:iam::123:role/test")
        client = resource._client

        mock_get_client.assert_called_once_with("ec2", region="us-east-1", role_arn="arn:aws:iam::123:role/test")
        assert client is mock_client

    @mock.patch("infrahouse_core.aws.base.get_client")
    def test_client_is_cached(self, mock_get_client):  # pylint: disable=unused-argument
        """_client is lazily created and reused on subsequent accesses."""
        mock_session = mock.MagicMock()
        mock_session.client.return_value = mock.MagicMock()

        resource = _ConcreteResource("res-1", "ec2", session=mock_session)
        client1 = resource._client
        client2 = resource._client

        assert client1 is client2
        mock_session.client.assert_called_once()


# ---------------------------------------------------------------------------
# AWSResource subclass (S3Bucket as representative)
# ---------------------------------------------------------------------------


class TestAWSResourceSubclassSession:
    """Session parameter is forwarded by AWSResource subclasses."""

    @mock.patch("infrahouse_core.aws.base.get_client")
    def test_s3_bucket_uses_session(self, mock_get_client):
        """S3Bucket creates its client from the session."""
        mock_session = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_session.client.return_value = mock_client

        bucket = S3Bucket("my-bucket", region="eu-west-1", session=mock_session)
        client = bucket._client

        mock_session.client.assert_called_once_with("s3", region_name="eu-west-1")
        mock_get_client.assert_not_called()
        assert client is mock_client

    @mock.patch("infrahouse_core.aws.base.get_client")
    def test_s3_bucket_backward_compatible(self, mock_get_client):
        """S3Bucket still works without a session (backward compatible)."""
        mock_client = mock.MagicMock()
        mock_get_client.return_value = mock_client

        bucket = S3Bucket("my-bucket", region="eu-west-1")
        client = bucket._client

        mock_get_client.assert_called_once_with("s3", region="eu-west-1", role_arn=None)
        assert client is mock_client


# ---------------------------------------------------------------------------
# EC2Instance
# ---------------------------------------------------------------------------


class TestEC2InstanceSession:
    """Session parameter on EC2Instance."""

    @mock.patch("infrahouse_core.aws.ec2_instance.get_client")
    def test_ec2_client_uses_session(self, mock_get_client):
        """ec2_client creates the client from the session."""
        mock_session = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_session.client.return_value = mock_client

        instance = EC2Instance("i-1234567890abcdef0", region="us-east-1", session=mock_session)
        client = instance.ec2_client

        mock_session.client.assert_called_once_with("ec2", region_name="us-east-1")
        mock_get_client.assert_not_called()
        assert client is mock_client

    @mock.patch("infrahouse_core.aws.ec2_instance.get_client")
    def test_ssm_client_uses_session(self, mock_get_client):
        """ssm_client creates the client from the session."""
        mock_session = mock.MagicMock()
        mock_ec2 = mock.MagicMock()
        mock_ssm = mock.MagicMock()
        mock_session.client.side_effect = lambda svc, **kw: mock_ssm if svc == "ssm" else mock_ec2

        instance = EC2Instance("i-1234567890abcdef0", region="us-east-1", session=mock_session)
        client = instance.ssm_client

        mock_session.client.assert_called_with("ssm", region_name="us-east-1")
        mock_get_client.assert_not_called()
        assert client is mock_ssm

    @mock.patch("infrahouse_core.aws.ec2_instance.get_client")
    def test_ec2_client_backward_compatible(self, mock_get_client):
        """ec2_client uses get_client when no session is provided."""
        mock_client = mock.MagicMock()
        mock_get_client.return_value = mock_client

        instance = EC2Instance("i-1234567890abcdef0", region="us-east-1")
        client = instance.ec2_client

        mock_get_client.assert_called_once_with("ec2", region="us-east-1", role_arn=None)
        assert client is mock_client


# ---------------------------------------------------------------------------
# ASG
# ---------------------------------------------------------------------------


class TestASGSession:
    """Session parameter on ASG."""

    @mock.patch("infrahouse_core.aws.asg.get_client")
    def test_autoscaling_client_uses_session(self, mock_get_client):
        """_autoscaling_client creates the client from the session."""
        mock_session = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_session.client.return_value = mock_client

        asg = ASG("my-asg", region="us-east-1", session=mock_session)
        client = asg._autoscaling_client

        mock_session.client.assert_called_once_with("autoscaling", region_name="us-east-1")
        mock_get_client.assert_not_called()
        assert client is mock_client

    def test_instances_passes_session(self):
        """ASG.instances passes session through to ASGInstance."""
        mock_session = mock.MagicMock()

        with (
            mock.patch.object(
                ASG,
                "_describe_auto_scaling_groups",
                new_callable=mock.PropertyMock,
                return_value={
                    "AutoScalingGroups": [
                        {
                            "Instances": [
                                {"InstanceId": "i-abc123"},
                            ],
                        }
                    ],
                },
            ),
            mock.patch.object(ASGInstance, "__init__", return_value=None) as mock_init,
        ):
            asg = ASG("my-asg", region="us-west-2", role_arn="arn:aws:iam::123:role/r", session=mock_session)
            instances = asg.instances

            assert len(instances) == 1
            mock_init.assert_called_once_with(
                instance_id="i-abc123",
                region="us-west-2",
                role_arn="arn:aws:iam::123:role/r",
                session=mock_session,
            )


# ---------------------------------------------------------------------------
# DynamoDBTable
# ---------------------------------------------------------------------------


class TestDynamoDBTableSession:
    """Session parameter on DynamoDBTable."""

    @mock.patch("infrahouse_core.aws.dynamodb.get_client")
    def test_dynamodb_client_uses_session(self, mock_get_client):
        """_dynamodb_client creates the client from the session."""
        mock_session = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_session.client.return_value = mock_client

        table = DynamoDBTable("my-table", region="us-east-1", session=mock_session)
        client = table._dynamodb_client

        mock_session.client.assert_called_once_with("dynamodb", region_name="us-east-1")
        mock_get_client.assert_not_called()
        assert client is mock_client

    @mock.patch("infrahouse_core.aws.dynamodb.get_resource")
    def test_table_resource_uses_session(self, mock_get_resource):
        """_table() creates the resource from the session."""
        mock_session = mock.MagicMock()
        mock_resource = mock.MagicMock()
        mock_table = mock.MagicMock()
        mock_session.resource.return_value = mock_resource
        mock_resource.Table.return_value = mock_table

        table = DynamoDBTable("my-table", region="us-east-1", session=mock_session)
        result = table._table()

        mock_session.resource.assert_called_once_with("dynamodb", region_name="us-east-1")
        mock_resource.Table.assert_called_once_with("my-table")
        mock_get_resource.assert_not_called()
        assert result is mock_table


# ---------------------------------------------------------------------------
# Zone (Route53)
# ---------------------------------------------------------------------------


class TestZoneSession:
    """Session parameter on Zone."""

    @mock.patch("infrahouse_core.aws.route53.zone.get_client")
    def test_route53_client_uses_session(self, mock_get_client):
        """_client creates the client from the session."""
        mock_session = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_session.client.return_value = mock_client

        zone = Zone(zone_id="Z12345", session=mock_session)
        client = zone._client

        mock_session.client.assert_called_once_with("route53", region_name=None)
        mock_get_client.assert_not_called()
        assert client is mock_client

    @mock.patch("infrahouse_core.aws.route53.zone.get_client")
    def test_route53_backward_compatible(self, mock_get_client):
        """_client uses get_client when no session is provided."""
        mock_client = mock.MagicMock()
        mock_get_client.return_value = mock_client

        zone = Zone(zone_id="Z12345", region="us-east-1")
        client = zone._client

        mock_get_client.assert_called_once_with("route53", region="us-east-1", role_arn=None)
        assert client is mock_client


# ---------------------------------------------------------------------------
# Secret (Secrets Manager)
# ---------------------------------------------------------------------------


class TestSecretSession:
    """Session parameter on Secret."""

    @mock.patch("infrahouse_core.aws.secretsmanager.get_client")
    def test_secretsmanager_client_uses_session(self, mock_get_client):
        """_client() creates the client from the session."""
        mock_session = mock.MagicMock()
        mock_client = mock.MagicMock()
        mock_session.client.return_value = mock_client

        secret = Secret("my-secret", region="us-east-1", session=mock_session)
        client = secret._client()

        mock_session.client.assert_called_once_with("secretsmanager", region_name="us-east-1")
        mock_get_client.assert_not_called()
        assert client is mock_client

    @mock.patch("infrahouse_core.aws.secretsmanager.get_client")
    def test_secretsmanager_backward_compatible(self, mock_get_client):
        """_client() uses get_client when no session is provided."""
        mock_client = mock.MagicMock()
        mock_get_client.return_value = mock_client

        secret = Secret("my-secret", region="us-east-1")
        client = secret._client()

        mock_get_client.assert_called_once_with("secretsmanager", role_arn=None, region="us-east-1")
        assert client is mock_client
