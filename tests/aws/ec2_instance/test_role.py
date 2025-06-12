from infrahouse_core.aws.ec2_instance import EC2Instance


def test_role():
    i = EC2Instance(region="us-west-2", role_arn="")
