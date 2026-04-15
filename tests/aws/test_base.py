"""Tests for AWSResource base class."""

from unittest import mock

import pytest

from infrahouse_core.aws.base import AWSResource

TEST_ARN = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/test"


class _TaggedResource(AWSResource):
    """Concrete subclass used to exercise the base tag helpers."""

    @property
    def exists(self) -> bool:
        return True

    def delete(self) -> None:
        pass

    @property
    def arn(self) -> str:
        return TEST_ARN


def _resource_with_mock_client():
    resource = _TaggedResource("test", "logs", region="us-east-1")
    client = mock.MagicMock()
    patcher = mock.patch.object(
        _TaggedResource,
        "_client",
        new_callable=mock.PropertyMock,
        return_value=client,
    )
    return resource, client, patcher


def test_cannot_instantiate():
    """AWSResource cannot be instantiated directly (abstract class)."""
    with pytest.raises(TypeError):
        AWSResource("some-id", "ec2", region="us-east-1")


def test_subclass_must_implement_both():
    """A subclass that only implements delete() still cannot be instantiated."""

    class PartialResource(AWSResource):
        def delete(self) -> None:
            pass

    with pytest.raises(TypeError):
        PartialResource("some-id", "ec2")


def test_complete_subclass():
    """A subclass implementing both exists and delete() can be instantiated."""

    class ConcreteResource(AWSResource):
        @property
        def exists(self) -> bool:
            return True

        def delete(self) -> None:
            pass

    resource = ConcreteResource("some-id", "ec2", region="us-east-1")
    assert resource.exists is True


# -- arn default --------------------------------------------------------------


def test_arn_default_not_implemented():
    """arn raises NotImplementedError unless a subclass implements it."""

    class NoArnResource(AWSResource):
        @property
        def exists(self) -> bool:
            return True

        def delete(self) -> None:
            pass

    resource = NoArnResource("some-id", "ec2")
    with pytest.raises(NotImplementedError, match="NoArnResource"):
        _ = resource.arn


# -- tags ---------------------------------------------------------------------


def test_tags_returns_mapping():
    """tags returns the dict from list_tags_for_resource."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {"Env": "prod", "Team": "core"}}
    with patcher:
        result = resource.tags
    assert result == {"Env": "prod", "Team": "core"}
    client.list_tags_for_resource.assert_called_once_with(resourceArn=TEST_ARN)


def test_tags_empty_when_missing():
    """tags returns an empty dict when list_tags_for_resource omits the key."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {}
    with patcher:
        assert resource.tags == {}


# -- set_tag ------------------------------------------------------------------


def test_set_tag_writes_when_absent():
    """set_tag writes the tag and returns True when the key is absent."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {}}
    with patcher:
        assert resource.set_tag("Env", "prod") is True
    client.tag_resource.assert_called_once_with(resourceArn=TEST_ARN, tags={"Env": "prod"})


def test_set_tag_writes_when_value_differs():
    """set_tag overwrites when the existing value differs."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {"Env": "dev"}}
    with patcher:
        assert resource.set_tag("Env", "prod") is True
    client.tag_resource.assert_called_once_with(resourceArn=TEST_ARN, tags={"Env": "prod"})


def test_set_tag_noop_when_current():
    """set_tag is a no-op when the tag already has the requested value."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {"Env": "prod"}}
    with patcher:
        assert resource.set_tag("Env", "prod") is False
    client.tag_resource.assert_not_called()


# -- set_tags -----------------------------------------------------------------


def test_set_tags_writes_only_changed():
    """set_tags writes only the tags whose value differs from current."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {"Env": "prod", "Team": "core"}}
    with patcher:
        written = resource.set_tags({"Env": "prod", "Team": "platform", "Owner": "ops"})
    assert written == 2
    client.tag_resource.assert_called_once_with(
        resourceArn=TEST_ARN,
        tags={"Team": "platform", "Owner": "ops"},
    )


def test_set_tags_noop_when_all_current():
    """set_tags makes no API call when all tags already match."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {"Env": "prod"}}
    with patcher:
        assert resource.set_tags({"Env": "prod"}) == 0
    client.tag_resource.assert_not_called()


# -- remove_tag ---------------------------------------------------------------


def test_remove_tag_when_present():
    """remove_tag removes the tag and returns True when it was set."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {"Env": "prod"}}
    with patcher:
        assert resource.remove_tag("Env") is True
    client.untag_resource.assert_called_once_with(resourceArn=TEST_ARN, tagKeys=["Env"])


def test_remove_tag_when_absent():
    """remove_tag is a no-op when the tag is not set."""
    resource, client, patcher = _resource_with_mock_client()
    client.list_tags_for_resource.return_value = {"tags": {}}
    with patcher:
        assert resource.remove_tag("Env") is False
    client.untag_resource.assert_not_called()
