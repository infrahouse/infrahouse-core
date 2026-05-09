import logging
import uuid

import boto3
import pytest
from botocore.exceptions import ClientError

LOG = logging.getLogger()

S3_REGION = "us-west-1"


@pytest.fixture
def s3_bucket():
    """
    Create a temporary S3 bucket for integration testing.

    Yields (bucket_name, region) tuple, then deletes the bucket after the test.
    Skips the test if the current AWS credentials lack the required permissions.
    """
    bucket_name = f"ih-core-test-{uuid.uuid4().hex[:8]}"
    s3 = boto3.client("s3", region_name=S3_REGION)

    try:
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": S3_REGION},
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("AccessDeniedException", "InvalidClientTokenId"):
            pytest.skip(f"AWS credentials not usable ({error_code}): {exc}")
        raise

    s3.get_waiter("bucket_exists").wait(Bucket=bucket_name)

    LOG.info("Created S3 bucket: %s", bucket_name)

    yield bucket_name, S3_REGION

    # Cleanup
    s3.delete_bucket(Bucket=bucket_name)
    LOG.info("Deleted S3 bucket: %s", bucket_name)