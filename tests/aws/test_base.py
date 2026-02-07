"""Tests for AWSResource base class."""

import pytest

from infrahouse_core.aws.base import AWSResource


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
