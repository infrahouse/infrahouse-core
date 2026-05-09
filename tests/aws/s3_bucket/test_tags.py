"""Integration tests for S3Bucket tag operations.

These tests require real AWS credentials and create/delete temporary buckets.
They are skipped automatically when credentials are not available.
"""

import os

import pytest

from infrahouse_core.aws.s3_bucket import S3Bucket

_AWS_CREDS = "AWS_ACCESS_KEY_ID" in os.environ and "AWS_SECRET_ACCESS_KEY" in os.environ


@pytest.mark.skipif(not _AWS_CREDS, reason="AWS credentials not set in environment")
def test_tags_empty_bucket(s3_bucket):
    """A newly created bucket with no tags returns an empty dict."""
    bucket_name, region = s3_bucket
    bucket = S3Bucket(bucket_name, region=region)
    assert bucket.tags == {}


@pytest.mark.skipif(not _AWS_CREDS, reason="AWS credentials not set in environment")
def test_tags_returns_bucket_tags(s3_bucket):
    """tags returns tags set on the bucket as a flat dict."""
    import boto3

    bucket_name, region = s3_bucket

    s3 = boto3.client("s3", region_name=region)
    s3.put_bucket_tagging(
        Bucket=bucket_name,
        Tagging={
            "TagSet": [
                {"Key": "Environment", "Value": "test"},
                {"Key": "vanta-exempt", "Value": "true"},
            ]
        },
    )

    bucket = S3Bucket(bucket_name, region=region)
    tags = bucket.tags
    assert tags == {"Environment": "test", "vanta-exempt": "true"}


@pytest.mark.skipif(not _AWS_CREDS, reason="AWS credentials not set in environment")
def test_set_tag(s3_bucket):
    """set_tag writes a single tag to the bucket."""
    bucket_name, region = s3_bucket
    bucket = S3Bucket(bucket_name, region=region)

    assert bucket.set_tag("Team", "platform") is True
    assert bucket.tags["Team"] == "platform"


@pytest.mark.skipif(not _AWS_CREDS, reason="AWS credentials not set in environment")
def test_set_tag_idempotent(s3_bucket):
    """set_tag returns False when the tag already has the requested value."""
    bucket_name, region = s3_bucket
    bucket = S3Bucket(bucket_name, region=region)

    bucket.set_tag("Team", "platform")
    assert bucket.set_tag("Team", "platform") is False


@pytest.mark.skipif(not _AWS_CREDS, reason="AWS credentials not set in environment")
def test_set_tags(s3_bucket):
    """set_tags writes multiple tags at once."""
    bucket_name, region = s3_bucket
    bucket = S3Bucket(bucket_name, region=region)

    written = bucket.set_tags({"Env": "dev", "Owner": "alice"})
    assert written == 2
    assert bucket.tags == {"Env": "dev", "Owner": "alice"}


@pytest.mark.skipif(not _AWS_CREDS, reason="AWS credentials not set in environment")
def test_remove_tag(s3_bucket):
    """remove_tag deletes a tag from the bucket."""
    bucket_name, region = s3_bucket
    bucket = S3Bucket(bucket_name, region=region)

    bucket.set_tag("ToRemove", "yes")
    assert bucket.remove_tag("ToRemove") is True
    assert "ToRemove" not in bucket.tags


@pytest.mark.skipif(not _AWS_CREDS, reason="AWS credentials not set in environment")
def test_remove_tag_absent(s3_bucket):
    """remove_tag returns False when the tag doesn't exist."""
    bucket_name, region = s3_bucket
    bucket = S3Bucket(bucket_name, region=region)

    assert bucket.remove_tag("nonexistent") is False