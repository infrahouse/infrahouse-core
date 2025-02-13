from unittest import mock

from infrahouse_core.aws.config import AWSConfig


def test_aws_home():
    with mock.patch("infrahouse_core.aws.config.osp.expanduser", return_value="/home/foo"):
        aws = AWSConfig()
        assert aws.aws_home == "/home/foo/.aws"
