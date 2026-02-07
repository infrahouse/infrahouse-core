"""Tests for S3Bucket.exists, S3Bucket.delete(), and _delete_all_objects."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.s3_bucket import S3Bucket

BUCKET_NAME = "my-test-bucket"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


# -- bucket_name property -----------------------------------------------------


def test_bucket_name():
    """bucket_name returns the name passed to the constructor."""
    bucket = S3Bucket(BUCKET_NAME)
    assert bucket.bucket_name == BUCKET_NAME


# -- exists -------------------------------------------------------------------


def test_exists_true():
    """exists returns True when the bucket is found."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.head_bucket.return_value = {}

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert bucket.exists is True
        mock_client.head_bucket.assert_called_once_with(Bucket=BUCKET_NAME)


def test_exists_false():
    """exists returns False when the bucket does not exist (404)."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.head_bucket.side_effect = _make_client_error("404", "Not Found")

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert bucket.exists is False


def test_exists_unexpected_error():
    """Unexpected errors from head_bucket are re-raised."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.head_bucket.side_effect = _make_client_error("403", "Forbidden")

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = bucket.exists
        assert exc_info.value.response["Error"]["Code"] == "403"


# -- delete (empty bucket) ---------------------------------------------------


def test_delete_empty_bucket():
    """delete() on an empty bucket deletes it directly."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"Versions": [], "DeleteMarkers": []}]
    )

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        bucket.delete()

    mock_client.delete_objects.assert_not_called()
    mock_client.delete_bucket.assert_called_once_with(Bucket=BUCKET_NAME)


# -- delete (bucket with versions and markers) --------------------------------


def test_delete_with_versions_and_markers():
    """delete() removes all object versions and delete markers before deleting the bucket."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [
            {
                "Versions": [
                    {"Key": "file1.txt", "VersionId": "v1"},
                    {"Key": "file2.txt", "VersionId": "v2"},
                ],
                "DeleteMarkers": [
                    {"Key": "file1.txt", "VersionId": "dm1"},
                ],
            }
        ]
    )

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        bucket.delete()

    # All 3 objects should be in a single batch
    mock_client.delete_objects.assert_called_once()
    call_args = mock_client.delete_objects.call_args
    assert call_args.kwargs["Bucket"] == BUCKET_NAME
    objects = call_args.kwargs["Delete"]["Objects"]
    assert len(objects) == 3
    assert {"Key": "file1.txt", "VersionId": "v1"} in objects
    assert {"Key": "file2.txt", "VersionId": "v2"} in objects
    assert {"Key": "file1.txt", "VersionId": "dm1"} in objects
    mock_client.delete_bucket.assert_called_once_with(Bucket=BUCKET_NAME)


# -- delete (multiple pages) --------------------------------------------------


def test_delete_with_pagination():
    """delete() handles multiple pages of object versions."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [
            {
                "Versions": [{"Key": "a.txt", "VersionId": "v1"}],
                "DeleteMarkers": [],
            },
            {
                "Versions": [],
                "DeleteMarkers": [{"Key": "b.txt", "VersionId": "dm1"}],
            },
        ]
    )

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        bucket.delete()

    # Two separate delete_objects calls — one per page
    assert mock_client.delete_objects.call_count == 2
    mock_client.delete_bucket.assert_called_once_with(Bucket=BUCKET_NAME)


# -- delete (batching > 1000 objects) -----------------------------------------


def test_delete_batches_large_pages():
    """delete() batches objects into groups of 1000 when a page has more."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()

    # Create a page with 2500 versions
    versions = [{"Key": f"obj-{i}", "VersionId": f"v{i}"} for i in range(2500)]
    mock_client.get_paginator.return_value = _mock_paginator(
        [{"Versions": versions, "DeleteMarkers": []}]
    )

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        bucket.delete()

    # 2500 objects / 1000 per batch = 3 calls
    assert mock_client.delete_objects.call_count == 3
    # First two batches have 1000, last has 500
    calls = mock_client.delete_objects.call_args_list
    assert len(calls[0].kwargs["Delete"]["Objects"]) == 1000
    assert len(calls[1].kwargs["Delete"]["Objects"]) == 1000
    assert len(calls[2].kwargs["Delete"]["Objects"]) == 500
    mock_client.delete_bucket.assert_called_once_with(Bucket=BUCKET_NAME)


# -- delete (non-existent bucket) ---------------------------------------------


def test_delete_not_exists_nosuchbucket():
    """delete() on a non-existent bucket is a no-op (NoSuchBucket)."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([])
    mock_client.delete_bucket.side_effect = _make_client_error("NoSuchBucket")

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        bucket.delete()  # Should not raise


def test_delete_not_exists_404():
    """delete() on a non-existent bucket is a no-op (404 string code)."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([])
    mock_client.delete_bucket.side_effect = _make_client_error("404")

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        bucket.delete()  # Should not raise


# -- delete (unexpected error) ------------------------------------------------


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([])
    mock_client.delete_bucket.side_effect = _make_client_error("AccessDenied")

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            bucket.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"


# -- delete (error during _delete_all_objects) --------------------------------


def test_delete_all_objects_error_propagates():
    """Errors from _delete_all_objects propagate if not NoSuchBucket."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()

    # Empty paginator so _delete_all_objects completes, but delete_bucket fails
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter([])
    mock_client.get_paginator.return_value = paginator
    mock_client.delete_bucket.side_effect = _make_client_error("InternalError")

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            bucket.delete()
        assert exc_info.value.response["Error"]["Code"] == "InternalError"


# -- delete (page with no Versions/DeleteMarkers keys) -----------------------


def test_delete_page_missing_keys():
    """delete() handles pages that lack Versions or DeleteMarkers keys."""
    bucket = S3Bucket(BUCKET_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    # Page with neither Versions nor DeleteMarkers key
    mock_client.get_paginator.return_value = _mock_paginator([{}])

    with mock.patch.object(S3Bucket, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        bucket.delete()

    mock_client.delete_objects.assert_not_called()
    mock_client.delete_bucket.assert_called_once_with(Bucket=BUCKET_NAME)
