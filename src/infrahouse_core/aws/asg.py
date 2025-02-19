"""
Module for ASG class - a class to work with Autoscaling group.
"""

from logging import getLogger
from typing import Dict, List

from botocore.exceptions import ClientError

from infrahouse_core.aws import get_client
from infrahouse_core.aws.asg_instance import ASGInstance

LOG = getLogger()


class ASG:
    """AWS Autoscaling group."""

    def __init__(self, asg_name: str, region: str = None):
        self._asg_name = asg_name
        self._region = region

    @property
    def instance_refreshes(self) -> List[Dict]:
        """
        :return: List of ASG instance refresh tasks.
        """
        return self._autoscaling_client.describe_instance_refreshes(
            AutoScalingGroupName=self._asg_name,
        )["InstanceRefreshes"]

    @property
    def instances(self) -> List[ASGInstance]:
        """
        :return: List of EC2 instances in the autoscaling group.
        """
        return [
            ASGInstance(instance_id=instance["InstanceId"], region=self._region)
            for instance in self._describe_auto_scaling_groups["AutoScalingGroups"][0]["Instances"]
        ]

    def cancel_instance_refresh(self):
        """Cancel all instance refreshes."""
        try:
            self._autoscaling_client.cancel_instance_refresh(AutoScalingGroupName=self._asg_name)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ActiveInstanceRefreshNotFound":
                LOG.warning(err)
            else:
                raise

    def complete_lifecycle_action(self, hook_name="terminating", result="CONTINUE", instance_id=None):
        """
        Completes the lifecycle hook.
        See details on https://docs.aws.amazon.com/autoscaling/ec2/userguide/completing-lifecycle-hooks.html

        :param hook_name: Hook name.
        :type hook_name: str
        :param result: Result of the hook. Can be either CONTINUE or ABANDON.
        :type result: str
        :param instance_id: EC2 instance_id for which complete the hook.
            If not given, assume the local instance.
        :type instance_id: str
        """
        self._autoscaling_client.complete_lifecycle_action(
            LifecycleHookName=hook_name,
            AutoScalingGroupName=self._asg_name,
            LifecycleActionResult=result,
            InstanceId=instance_id or ASGInstance().instance_id,
        )

    def record_lifecycle_action_heartbeat(self, hook_name="terminating", instance_id=None):
        """
        Extend lifecycle wait time.

        :param hook_name: Hook name.
        :type hook_name: str
        :param instance_id: EC2 instance_id for which the hook is waiting.
            If not given, assume the local instance.
        :type instance_id: str
        """
        self._autoscaling_client.record_lifecycle_action_heartbeat(
            LifecycleHookName=hook_name,
            AutoScalingGroupName=self._asg_name,
            InstanceId=instance_id or ASGInstance().instance_id,
        )

    @property
    def _autoscaling_client(self):
        return get_client("autoscaling", region=self._region)

    @property
    def _describe_auto_scaling_groups(self):
        return self._autoscaling_client.describe_auto_scaling_groups(
            AutoScalingGroupNames=[
                self._asg_name,
            ],
        )
