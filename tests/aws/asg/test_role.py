from unittest import mock

from infrahouse_core.aws.asg import ASG
from infrahouse_core.aws.asg_instance import ASGInstance


def test_instances():
    with (
        mock.patch.object(
            ASG,
            "_describe_auto_scaling_groups",
            new_callable=mock.PropertyMock,
            return_value={
                "AutoScalingGroups": [
                    {
                        "AutoScalingGroupARN": "arn:aws:autoscaling:us-west-2:303467602807:autoScalingGroup:c474da20-45f0-4cdf-948a-057360b43f79:autoScalingGroupName/update-dns-wIIbUFvBKQS8w3kzJLYbkhu2EDBYoijP",
                        "AutoScalingGroupName": "update-dns-wIIbUFvBKQS8w3kzJLYbkhu2EDBYoijP",
                        "AvailabilityZoneDistribution": {"CapacityDistributionStrategy": "balanced-best-effort"},
                        "AvailabilityZones": ["us-west-2a", "us-west-2b", "us-west-2d"],
                        "CapacityReservationSpecification": {"CapacityReservationPreference": "default"},
                        "DefaultCooldown": 300,
                        "DesiredCapacity": 1,
                        "EnabledMetrics": [],
                        "HealthCheckGracePeriod": 300,
                        "HealthCheckType": "EC2",
                        "Instances": [
                            {
                                "AvailabilityZone": "us-west-2b",
                                "HealthStatus": "Healthy",
                                "InstanceId": "i-0d02e8a467749ad97",
                                "InstanceType": "t3.micro",
                                "LaunchTemplate": {
                                    "LaunchTemplateId": "lt-0760f7044343bb155",
                                    "LaunchTemplateName": "update-dns-20250612135112430400000004",
                                    "Version": "1",
                                },
                                "LifecycleState": "InService",
                                "ProtectedFromScaleIn": False,
                            }
                        ],
                        "LaunchTemplate": {
                            "LaunchTemplateId": "lt-0760f7044343bb155",
                            "LaunchTemplateName": "update-dns-20250612135112430400000004",
                            "Version": "1",
                        },
                        "LoadBalancerNames": [],
                        "MaxSize": 1,
                        "MinSize": 1,
                        "NewInstancesProtectedFromScaleIn": False,
                        "ServiceLinkedRoleARN": "arn:aws:iam::303467602807:role/aws-service-role/autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling",
                        "SuspendedProcesses": [],
                        "Tags": [
                            {
                                "Key": "update-dns-rule",
                                "PropagateAtLaunch": True,
                                "ResourceId": "update-dns-wIIbUFvBKQS8w3kzJLYbkhu2EDBYoijP",
                                "ResourceType": "auto-scaling-group",
                                "Value": "update-dns-test",
                            }
                        ],
                        "TargetGroupARNs": [],
                        "TerminationPolicies": ["Default"],
                        "TrafficSources": [],
                        "VPCZoneIdentifier": "subnet-094daac4cfed0dfb1,subnet-08f55c666a4410dc6,subnet-0164b5d3b7d3fc912",
                    }
                ],
                # "ResponseMetadata": {
                #     "HTTPHeaders": {
                #         "content-length": "3384",
                #         "content-type": "text/xml",
                #         "date": "Thu, 12 Jun 2025 14:50:57 GMT",
                #         "x-amzn-requestid": "45856487-815a-4d13-b380-8ffff8f74b2d",
                #     },
                #     "HTTPStatusCode": 200,
                #     "RequestId": "45856487-815a-4d13-b380-8ffff8f74b2d",
                #     "RetryAttempts": 0,
                # },
            },
        ),
        mock.patch.object(ASGInstance, "__init__", return_value=None) as mock_asg_instance,
    ):
        asg = ASG("foo-asg", role_arn="foo")
        assert len(asg.instances) > 0
        mock_asg_instance.assert_called_once_with(instance_id="i-0d02e8a467749ad97", region=None, role_arn="foo")
