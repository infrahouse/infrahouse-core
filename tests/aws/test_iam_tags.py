"""Unit tests for the IAM-native tag helpers and ``arn`` on the IAM resource classes.

IAM has no ``list_tags_for_resource``; each taggable IAM entity has its own
``list_*_tags`` / ``tag_*`` / ``untag_*`` calls.  The parametrized tests run
once per class in :data:`SPECS`, so each class is checked against its own API.
IAM groups can't be tagged; the tests at the end cover what ``IAMGroup`` does.
"""

from dataclasses import dataclass
from typing import Optional
from unittest import mock

import pytest
from botocore import xform_name
from botocore.exceptions import ClientError
from botocore.loaders import create_loader
from botocore.model import ServiceModel

from infrahouse_core.aws.iam_group import IAMGroup
from infrahouse_core.aws.iam_instance_profile import IAMInstanceProfile
from infrahouse_core.aws.iam_policy import IAMPolicy
from infrahouse_core.aws.iam_role import IAMRole
from infrahouse_core.aws.iam_user import IAMUser

POLICY_ARN = "arn:aws:iam::123456789012:policy/my-policy"


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
    IAMTagSpec(IAMUser, "my-user", "UserName", "list_user_tags", "tag_user", "untag_user", "get_user", "User"),
    IAMTagSpec(IAMPolicy, POLICY_ARN, "PolicyArn", "list_policy_tags", "tag_policy", "untag_policy", None, None),
    IAMTagSpec(
        IAMInstanceProfile,
        "my-profile",
        "InstanceProfileName",
        "list_instance_profile_tags",
        "tag_instance_profile",
        "untag_instance_profile",
        "get_instance_profile",
        "InstanceProfile",
    ),
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
def test_spec_matches_botocore(spec, monkeypatch):
    """The operation and parameter names the tests expect exist in botocore's IAM model.

    The model comes from botocore's data files, not from a client or session, so no AWS config is read. The
    profile below doesn't exist: building a client or session here would fail with ``ProfileNotFound``.
    """
    monkeypatch.setenv("AWS_PROFILE", "infrahouse-core-unit-tests-no-such-profile")
    loader = create_loader()
    model = ServiceModel(loader.load_service_model("iam", "service-2"))
    paginators = loader.load_service_model("iam", "paginators-1")["pagination"]
    api_names = {xform_name(op): op for op in model.operation_names}

    def input_members(op):
        return set(model.operation_model(api_names[op]).input_shape.members)

    assert api_names[spec.list_op] in paginators
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


def test_policy_arn_is_resource_id():
    """IAMPolicy is constructed from its ARN, so ``arn`` makes no API call."""
    client = mock.MagicMock()

    with mock.patch.object(IAMPolicy, "_client", new_callable=mock.PropertyMock, return_value=client):
        assert IAMPolicy(POLICY_ARN).arn == POLICY_ARN

    assert not client.mock_calls


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


# -- IAMGroup ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda g: g.tags, id="tags"),
        pytest.param(lambda g: g.set_tag("Env", "prod"), id="set_tag"),
        pytest.param(lambda g: g.set_tags({"Env": "prod"}), id="set_tags"),
        pytest.param(lambda g: g.remove_tag("Env"), id="remove_tag"),
    ],
)
def test_group_tag_helpers_say_groups_cannot_be_tagged(call):
    """IAM has no tag API for groups; the helpers say so instead of "does not implement arn"."""
    client = mock.MagicMock()

    with mock.patch.object(IAMGroup, "_client", new_callable=mock.PropertyMock, return_value=client):
        with pytest.raises(NotImplementedError, match="IAM group my-group can't be tagged"):
            call(IAMGroup("my-group"))

    assert not client.mock_calls
