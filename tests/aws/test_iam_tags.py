"""Unit tests for the IAM-native tag helpers and ``arn`` on the IAM resource classes.

IAM has no ``list_tags_for_resource``; each taggable IAM entity has its own
``list_*_tags`` / ``tag_*`` / ``untag_*`` calls.  Every test here runs once per
class in :data:`SPECS`, so each class is checked against its own API.
"""

from dataclasses import dataclass
from typing import Optional
from unittest import mock

import boto3
import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.iam_role import IAMRole


@dataclass(frozen=True)
class IAMTagSpec:
    """How one IAM class is expected to call its tag API."""

    cls: type
    resource_id: str
    id_param: str
    list_op: str
    tag_op: str
    untag_op: str
    # ``get_*`` call and response key that hold the ARN; ``None`` if the resource id is the ARN.
    get_op: Optional[str]
    get_key: Optional[str]

    def __str__(self):
        return self.cls.__name__


SPECS = [
    IAMTagSpec(IAMRole, "my-role", "RoleName", "list_role_tags", "tag_role", "untag_role", "get_role", "Role"),
]
SPECS_WITH_GET = [spec for spec in SPECS if spec.get_op]


def _make_client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "test_operation")


def _page(tags, truncated=False):
    """Return one ``list_*_tags`` response page."""
    page = {"Tags": [{"Key": k, "Value": v} for k, v in tags.items()], "IsTruncated": truncated}
    if truncated:
        page["Marker"] = "next-page"
    return page


def _client_with_pages(*pages):
    """Return a mock IAM client whose ``list_*_tags`` paginator yields ``pages`` on every call."""
    client = mock.MagicMock()
    client.get_paginator.return_value.paginate.side_effect = lambda **_: iter(pages)
    return client


def _client_with_tags(tags):
    return _client_with_pages(_page(tags))


def _client_raising(error):
    """Return a mock IAM client whose ``list_*_tags`` paginator raises ``error`` when iterated."""

    def pages(**_):
        raise error
        yield  # pylint: disable=unreachable

    client = mock.MagicMock()
    client.get_paginator.return_value.paginate.side_effect = pages
    return client


def _patch_client(spec, client):
    return mock.patch.object(spec.cls, "_client", new_callable=mock.PropertyMock, return_value=client)


def _resource(spec):
    return spec.cls(spec.resource_id, region="us-east-1")


def _id(spec):
    return {spec.id_param: spec.resource_id}


def _assert_no_writes(spec, client):
    getattr(client, spec.tag_op).assert_not_called()
    getattr(client, spec.untag_op).assert_not_called()


parametrize_specs = pytest.mark.parametrize("spec", SPECS, ids=str)


# -- the spec table matches botocore ---------------------------------------------


@parametrize_specs
def test_spec_matches_botocore(spec):
    """The operation and parameter names the tests expect exist in botocore's IAM model."""
    client = boto3.client("iam", region_name="us-east-1")
    model = client.meta.service_model

    def input_members(op):
        return set(model.operation_model(client.meta.method_to_api_mapping[op]).input_shape.members)

    assert client.can_paginate(spec.list_op)
    assert spec.id_param in input_members(spec.list_op)
    assert {spec.id_param, "Tags"} <= input_members(spec.tag_op)
    assert {spec.id_param, "TagKeys"} <= input_members(spec.untag_op)
    if spec.get_op:
        assert spec.id_param in input_members(spec.get_op)


# -- arn ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", SPECS_WITH_GET, ids=str)
def test_arn_from_get_response(spec):
    arn = f"arn:aws:iam::123456789012:{spec.resource_id}"
    client = mock.MagicMock()
    getattr(client, spec.get_op).return_value = {spec.get_key: {"Arn": arn}}

    with _patch_client(spec, client):
        assert _resource(spec).arn == arn

    getattr(client, spec.get_op).assert_called_once_with(**_id(spec))


@pytest.mark.parametrize("spec", SPECS_WITH_GET, ids=str)
def test_arn_no_such_entity_propagates(spec):
    client = mock.MagicMock()
    getattr(client, spec.get_op).side_effect = _make_client_error("NoSuchEntity")

    with _patch_client(spec, client):
        with pytest.raises(ClientError) as exc_info:
            _ = _resource(spec).arn

    assert exc_info.value.response["Error"]["Code"] == "NoSuchEntity"


# -- tags --------------------------------------------------------------------------


def test_role_tags_no_longer_raises_not_implemented():
    """Regression for #151: ``IAMRole(...).tags`` raised ``NotImplementedError: IAMRole does not implement arn``."""
    client = _client_with_tags({"Env": "prod"})

    with mock.patch.object(IAMRole, "_client", new_callable=mock.PropertyMock, return_value=client):
        assert IAMRole("my-role").tags == {"Env": "prod"}


@parametrize_specs
def test_tags_reads_every_page(spec):
    client = _client_with_pages(
        _page({"Env": "prod", "Team": "platform"}, truncated=True),
        _page({"Owner": "alice"}),
    )

    with _patch_client(spec, client):
        assert _resource(spec).tags == {"Env": "prod", "Team": "platform", "Owner": "alice"}

    client.get_paginator.assert_called_once_with(spec.list_op)
    client.get_paginator.return_value.paginate.assert_called_once_with(**_id(spec))


@parametrize_specs
def test_tags_empty(spec):
    client = _client_with_tags({})

    with _patch_client(spec, client):
        assert _resource(spec).tags == {}


@parametrize_specs
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda r: r.tags, id="tags"),
        pytest.param(lambda r: r.set_tag("Env", "prod"), id="set_tag"),
        pytest.param(lambda r: r.set_tags({"Env": "prod"}), id="set_tags"),
        pytest.param(lambda r: r.remove_tag("Env"), id="remove_tag"),
    ],
)
def test_no_such_entity_propagates(spec, call):
    """A missing entity raises ``NoSuchEntity``; the helpers don't treat it as "no tags"."""
    client = _client_raising(_make_client_error("NoSuchEntity"))

    with _patch_client(spec, client):
        with pytest.raises(ClientError) as exc_info:
            call(_resource(spec))

    assert exc_info.value.response["Error"]["Code"] == "NoSuchEntity"
    _assert_no_writes(spec, client)


# -- set_tag -----------------------------------------------------------------------


@parametrize_specs
def test_set_tag_writes_only_the_new_tag(spec):
    client = _client_with_tags({"Env": "prod"})

    with _patch_client(spec, client):
        assert _resource(spec).set_tag("Team", "platform") is True

    getattr(client, spec.tag_op).assert_called_once_with(**_id(spec), Tags=[{"Key": "Team", "Value": "platform"}])
    getattr(client, spec.untag_op).assert_not_called()


@parametrize_specs
def test_set_tag_overwrites_changed_value(spec):
    client = _client_with_tags({"Env": "dev", "Team": "platform"})

    with _patch_client(spec, client):
        assert _resource(spec).set_tag("Env", "prod") is True

    getattr(client, spec.tag_op).assert_called_once_with(**_id(spec), Tags=[{"Key": "Env", "Value": "prod"}])


@parametrize_specs
def test_set_tag_unchanged_makes_no_call(spec):
    client = _client_with_tags({"Env": "prod"})

    with _patch_client(spec, client):
        assert _resource(spec).set_tag("Env", "prod") is False

    _assert_no_writes(spec, client)


# -- set_tags ----------------------------------------------------------------------


@parametrize_specs
def test_set_tags_writes_only_changed(spec):
    client = _client_with_tags({"A": "1", "B": "old"})

    with _patch_client(spec, client):
        assert _resource(spec).set_tags({"A": "1", "B": "new", "C": "3"}) == 2

    getattr(client, spec.tag_op).assert_called_once_with(
        **_id(spec), Tags=[{"Key": "B", "Value": "new"}, {"Key": "C", "Value": "3"}]
    )
    getattr(client, spec.untag_op).assert_not_called()


@parametrize_specs
def test_set_tags_unchanged_makes_no_call(spec):
    client = _client_with_tags({"A": "1", "B": "2"})

    with _patch_client(spec, client):
        assert _resource(spec).set_tags({"A": "1", "B": "2"}) == 0

    _assert_no_writes(spec, client)


@parametrize_specs
def test_set_tags_empty_makes_no_call(spec):
    client = _client_with_tags({"A": "1"})

    with _patch_client(spec, client):
        assert _resource(spec).set_tags({}) == 0

    _assert_no_writes(spec, client)


# -- remove_tag --------------------------------------------------------------------


@parametrize_specs
def test_remove_tag_present(spec):
    client = _client_with_tags({"Env": "prod", "Team": "platform"})

    with _patch_client(spec, client):
        assert _resource(spec).remove_tag("Env") is True

    getattr(client, spec.untag_op).assert_called_once_with(**_id(spec), TagKeys=["Env"])
    getattr(client, spec.tag_op).assert_not_called()


@parametrize_specs
def test_remove_tag_missing_makes_no_call(spec):
    client = _client_with_tags({"Team": "platform"})

    with _patch_client(spec, client):
        assert _resource(spec).remove_tag("Env") is False

    _assert_no_writes(spec, client)
