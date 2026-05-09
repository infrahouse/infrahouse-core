"""Unit tests for S3Bucket tag overrides."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.s3_bucket import S3Bucket

BUCKET_NAME = "my-test-bucket"


def _make_client_error(code, message="test"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def _patch_client(mock_client):
    return mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client)


# -- tags property -------------------------------------------------------------


def test_tags_returns_flat_dict():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [
            {"Key": "Env", "Value": "prod"},
            {"Key": "Team", "Value": "platform"},
        ]
    }

    with _patch_client(mock_client):
        assert bucket.tags == {"Env": "prod", "Team": "platform"}

    mock_client.get_bucket_tagging.assert_called_once_with(Bucket=BUCKET_NAME)


def test_tags_no_tagset_returns_empty():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.side_effect = _make_client_error("NoSuchTagSet")

    with _patch_client(mock_client):
        assert bucket.tags == {}


def test_tags_unexpected_error_propagates():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.side_effect = _make_client_error("AccessDenied")

    with _patch_client(mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = bucket.tags
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- set_tag -------------------------------------------------------------------


def test_set_tag_writes_new_tag():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.side_effect = _make_client_error("NoSuchTagSet")

    with _patch_client(mock_client):
        assert bucket.set_tag("Env", "dev") is True

    mock_client.put_bucket_tagging.assert_called_once_with(
        Bucket=BUCKET_NAME,
        Tagging={"TagSet": [{"Key": "Env", "Value": "dev"}]},
    )


def test_set_tag_preserves_existing_tags():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "Existing", "Value": "yes"}]
    }

    with _patch_client(mock_client):
        assert bucket.set_tag("New", "val") is True

    call_args = mock_client.put_bucket_tagging.call_args
    tag_set = call_args.kwargs["Tagging"]["TagSet"]
    tag_dict = {t["Key"]: t["Value"] for t in tag_set}
    assert tag_dict == {"Existing": "yes", "New": "val"}


def test_set_tag_idempotent():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "Env", "Value": "prod"}]
    }

    with _patch_client(mock_client):
        assert bucket.set_tag("Env", "prod") is False

    mock_client.put_bucket_tagging.assert_not_called()


def test_set_tag_overwrites_value():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "Env", "Value": "dev"}]
    }

    with _patch_client(mock_client):
        assert bucket.set_tag("Env", "prod") is True

    call_args = mock_client.put_bucket_tagging.call_args
    tag_set = call_args.kwargs["Tagging"]["TagSet"]
    assert tag_set == [{"Key": "Env", "Value": "prod"}]


# -- set_tags ------------------------------------------------------------------


def test_set_tags_writes_multiple():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.side_effect = _make_client_error("NoSuchTagSet")

    with _patch_client(mock_client):
        assert bucket.set_tags({"A": "1", "B": "2"}) == 2

    call_args = mock_client.put_bucket_tagging.call_args
    tag_set = call_args.kwargs["Tagging"]["TagSet"]
    tag_dict = {t["Key"]: t["Value"] for t in tag_set}
    assert tag_dict == {"A": "1", "B": "2"}


def test_set_tags_skips_unchanged():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "A", "Value": "1"}, {"Key": "B", "Value": "2"}]
    }

    with _patch_client(mock_client):
        assert bucket.set_tags({"A": "1", "B": "2"}) == 0

    mock_client.put_bucket_tagging.assert_not_called()


def test_set_tags_partial_update():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "A", "Value": "1"}, {"Key": "B", "Value": "old"}]
    }

    with _patch_client(mock_client):
        assert bucket.set_tags({"A": "1", "B": "new", "C": "3"}) == 2

    call_args = mock_client.put_bucket_tagging.call_args
    tag_set = call_args.kwargs["Tagging"]["TagSet"]
    tag_dict = {t["Key"]: t["Value"] for t in tag_set}
    assert tag_dict == {"A": "1", "B": "new", "C": "3"}


# -- remove_tag ----------------------------------------------------------------


def test_remove_tag_deletes():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "Env", "Value": "dev"}, {"Key": "Team", "Value": "x"}]
    }

    with _patch_client(mock_client):
        assert bucket.remove_tag("Env") is True

    call_args = mock_client.put_bucket_tagging.call_args
    tag_set = call_args.kwargs["Tagging"]["TagSet"]
    assert tag_set == [{"Key": "Team", "Value": "x"}]
    mock_client.delete_bucket_tagging.assert_not_called()


def test_remove_last_tag_deletes_tagging():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.return_value = {
        "TagSet": [{"Key": "Only", "Value": "one"}]
    }

    with _patch_client(mock_client):
        assert bucket.remove_tag("Only") is True

    mock_client.put_bucket_tagging.assert_not_called()
    mock_client.delete_bucket_tagging.assert_called_once_with(Bucket=BUCKET_NAME)


def test_remove_tag_absent():
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_bucket_tagging.side_effect = _make_client_error("NoSuchTagSet")

    with _patch_client(mock_client):
        assert bucket.remove_tag("nope") is False

    mock_client.put_bucket_tagging.assert_not_called()
    mock_client.delete_bucket_tagging.assert_not_called()