"""Tests for ASG.tags and ASG.launch_tags."""

from unittest import mock

from infrahouse_core.aws.asg import ASG

DESCRIBE_RESPONSE = {
    "AutoScalingGroups": [
        {
            "AutoScalingGroupName": "my-asg",
            "Tags": [
                {"Key": "Name", "Value": "my-asg", "PropagateAtLaunch": True},
                {"Key": "environment", "Value": "development", "PropagateAtLaunch": True},
                {"Key": "created_by", "Value": "terraform", "PropagateAtLaunch": False},
            ],
        }
    ]
}


def _asg_with_response(response):
    """Return an ASG whose describe_auto_scaling_groups() returns the given response."""
    asg = ASG("my-asg", region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_auto_scaling_groups.return_value = response
    return asg, mock_client


def test_tags():
    """tags returns all ASG tags as a {key: value} dictionary."""
    asg, mock_client = _asg_with_response(DESCRIBE_RESPONSE)
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert asg.tags == {
            "Name": "my-asg",
            "environment": "development",
            "created_by": "terraform",
        }


def test_tags_empty():
    """tags returns an empty dictionary when the ASG has no tags."""
    asg, mock_client = _asg_with_response({"AutoScalingGroups": [{"AutoScalingGroupName": "my-asg", "Tags": []}]})
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert asg.tags == {}


def test_launch_tags():
    """launch_tags returns only the tags propagated to instances at launch."""
    asg, mock_client = _asg_with_response(DESCRIBE_RESPONSE)
    with mock.patch.object(ASG, "_autoscaling_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert asg.launch_tags == {
            "Name": "my-asg",
            "environment": "development",
        }
