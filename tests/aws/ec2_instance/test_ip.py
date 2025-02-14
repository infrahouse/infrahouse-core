from unittest import mock

from infrahouse_core.aws.ec2_instance import EC2Instance


def test_private_ip():
    with mock.patch.object(
        EC2Instance,
        "_describe_instance",
        new_callable=mock.PropertyMock,
        return_value={
            "PrivateIpAddress": "10.1.100.199",
        },
    ):
        instance = EC2Instance(instance_id="i-0193c1708ae96e8a3")
        assert instance.private_ip == "10.1.100.199"


def test_private_hostname():
    with mock.patch.object(
        EC2Instance,
        "_describe_instance",
        new_callable=mock.PropertyMock,
        return_value={
            "Architecture": "x86_64",
            "BlockDeviceMappings": [
                {
                    "DeviceName": "/dev/sda1",
                    "Ebs": {
                        "DeleteOnTermination": True,
                        "Status": "attached",
                        "VolumeId": "vol-02531afdc8ccef651",
                    },
                }
            ],
            "ClientToken": "30f65405-0f90-2895-a79b-f1baddf0f846",
            "EbsOptimized": False,
            "EnaSupport": True,
            "Hypervisor": "xen",
            "NetworkInterfaces": [
                {
                    "Attachment": {
                        "AttachmentId": "eni-attach-0a2d110c46f2f8e3e",
                        "DeleteOnTermination": True,
                        "DeviceIndex": 0,
                        "Status": "attached",
                        "NetworkCardIndex": 0,
                    },
                    "Description": "",
                    "Groups": [{"GroupId": "sg-095f56cc312a2da13", "GroupName": "default"}],
                    "Ipv6Addresses": [],
                    "MacAddress": "12:39:08:d8:1d:cb",
                    "NetworkInterfaceId": "eni-0bb23eef94807eb08",
                    "OwnerId": "303467602807",
                    "PrivateIpAddress": "10.1.100.198",
                    "PrivateIpAddresses": [{"Primary": True, "PrivateIpAddress": "10.1.100.198"}],
                    "SourceDestCheck": True,
                    "Status": "in-use",
                    "SubnetId": "subnet-03bc2f51b19ed15f8",
                    "VpcId": "vpc-0f7715072373df2cb",
                    "InterfaceType": "interface",
                    "Operator": {"Managed": False},
                }
            ],
            "RootDeviceName": "/dev/sda1",
            "RootDeviceType": "ebs",
            "SecurityGroups": [{"GroupId": "sg-095f56cc312a2da13", "GroupName": "default"}],
            "SourceDestCheck": True,
            "Tags": [
                {"Key": "aws:ec2launchtemplate:version", "Value": "1"},
                {"Key": "aws:autoscaling:groupName", "Value": "update-dns-ZR0yIRGnkLo77JbMxA1ZCbBTrZw3wv42"},
                {"Key": "Name", "Value": "ip-10-1-100-198"},
                {"Key": "update-dns-rule", "Value": "_PrivateDnsName_"},
                {"Key": "PrivateIpAddress", "Value": "10.1.100.198"},
                {"Key": "aws:ec2launchtemplate:id", "Value": "lt-09d595e001d05cec5"},
            ],
            "VirtualizationType": "hvm",
            "CpuOptions": {"CoreCount": 1, "ThreadsPerCore": 2},
            "CapacityReservationSpecification": {"CapacityReservationPreference": "open"},
            "HibernationOptions": {"Configured": False},
            "MetadataOptions": {
                "State": "applied",
                "HttpTokens": "optional",
                "HttpPutResponseHopLimit": 1,
                "HttpEndpoint": "enabled",
                "HttpProtocolIpv6": "disabled",
                "InstanceMetadataTags": "disabled",
            },
            "EnclaveOptions": {"Enabled": False},
            "BootMode": "uefi-preferred",
            "PlatformDetails": "Linux/UNIX",
            "UsageOperation": "RunInstances",
            "PrivateDnsNameOptions": {
                "HostnameType": "ip-name",
                "EnableResourceNameDnsARecord": False,
                "EnableResourceNameDnsAAAARecord": False,
            },
            "MaintenanceOptions": {"AutoRecovery": "default"},
            "CurrentInstanceBootMode": "uefi",
            "NetworkPerformanceOptions": {"BandwidthWeighting": "default"},
            "Operator": {"Managed": False},
            "InstanceId": "i-0193c1708ae96e8a3",
            "ImageId": "ami-0e1bed4f06a3b463d",
            "State": {"Code": 16, "Name": "running"},
            "PrivateDnsName": "ip-10-1-100-198.ec2.internal",
            "PublicDnsName": "",
            "StateTransitionReason": "",
            "AmiLaunchIndex": 0,
            "ProductCodes": [],
            "InstanceType": "t3.micro",
            "Placement": {"GroupName": "", "Tenancy": "default", "AvailabilityZone": "us-east-1a"},
            "Monitoring": {"State": "disabled"},
            "SubnetId": "subnet-03bc2f51b19ed15f8",
            "VpcId": "vpc-0f7715072373df2cb",
            "PrivateIpAddress": "10.1.100.198",
        },
    ):
        instance = EC2Instance(instance_id="i-0193c1708ae96e8a3")
        assert instance.hostname == "ip-10-1-100-198"
        assert instance.tags["PrivateIpAddress"] == "10.1.100.198"


def test_hostname_none():
    mock_response = {
        "Architecture": "x86_64",
        "BlockDeviceMappings": [],
        "ClientToken": "c9965413-d911-013c-44e6-85db4c6f3e22",
        "EbsOptimized": False,
        "EnaSupport": True,
        "Hypervisor": "xen",
        "NetworkInterfaces": [],
        "RootDeviceName": "/dev/sda1",
        "RootDeviceType": "ebs",
        "SecurityGroups": [],
        "StateReason": {
            "Code": "Client.UserInitiatedShutdown",
            "Message": "Client.UserInitiatedShutdown: User initiated shutdown",
        },
        "Tags": [
            {"Key": "aws:autoscaling:groupName", "Value": "update-dns-ZR0yIRGnkLo77JbMxA1ZCbBTrZw3wv42"},
            {"Key": "aws:ec2launchtemplate:version", "Value": "1"},
            {"Key": "aws:ec2launchtemplate:id", "Value": "lt-09d595e001d05cec5"},
            {"Key": "update-dns-rule", "Value": "_PrivateDnsName_"},
        ],
        "VirtualizationType": "hvm",
        "CpuOptions": {"CoreCount": 1, "ThreadsPerCore": 2},
        "CapacityReservationSpecification": {"CapacityReservationPreference": "open"},
        "HibernationOptions": {"Configured": False},
        "MetadataOptions": {
            "State": "pending",
            "HttpTokens": "optional",
            "HttpPutResponseHopLimit": 1,
            "HttpEndpoint": "enabled",
            "HttpProtocolIpv6": "disabled",
            "InstanceMetadataTags": "disabled",
        },
        "EnclaveOptions": {"Enabled": False},
        "BootMode": "uefi-preferred",
        "PlatformDetails": "Linux/UNIX",
        "UsageOperation": "RunInstances",
        "MaintenanceOptions": {"AutoRecovery": "default"},
        "CurrentInstanceBootMode": "uefi",
        "NetworkPerformanceOptions": {"BandwidthWeighting": "default"},
        "Operator": {"Managed": False},
        "InstanceId": "i-07542dd0efab4b51a",
        "ImageId": "ami-0e1bed4f06a3b463d",
        "State": {"Code": 48, "Name": "terminated"},
        "PrivateDnsName": "",
        "PublicDnsName": "",
        "StateTransitionReason": "User initiated (2025-02-14 16:34:34 GMT)",
        "AmiLaunchIndex": 0,
        "ProductCodes": [],
        "InstanceType": "t3.micro",
        "Placement": {"GroupName": "", "Tenancy": "default", "AvailabilityZone": "us-east-1f"},
        "Monitoring": {"State": "disabled"},
    }
    with mock.patch.object(
        EC2Instance, "_describe_instance", new_callable=mock.PropertyMock, return_value=mock_response
    ):
        instance = EC2Instance(instance_id="i-07542dd0efab4b51a")
        assert instance.hostname is None
