"""Probe what the sandbox creds can do for EC2 provisioning (both allowed regions)."""
import os, sys
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

REGIONS = ["us-east-1", "us-west-2"]


def probe(region):
    print(f"\n--- {region} ---")
    try:
        ec2 = boto3.client("ec2", region_name=region)
        # cheap read calls to confirm reachability + perms
        az = ec2.describe_availability_zones()["AvailabilityZones"]
        print(f"  describe_availability_zones: OK ({len(az)} AZs)")
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
        print(f"  default VPC: {vpcs[0]['VpcId'] if vpcs else 'NONE'}")
        # find a recent Ubuntu 24.04 AMI (Canonical owner 099720109477)
        imgs = ec2.describe_images(
            Owners=["099720109477"],
            Filters=[
                {"Name": "name", "Values": ["ubuntu/images/hvm-ssd*/ubuntu-noble-24.04-amd64-server-*"]},
                {"Name": "state", "Values": ["available"]},
            ])["Images"]
        imgs.sort(key=lambda i: i["CreationDate"], reverse=True)
        if imgs:
            print(f"  Ubuntu 24.04 AMI: {imgs[0]['ImageId']}  ({imgs[0]['Name'][:50]})")
        else:
            print("  Ubuntu 24.04 AMI: none found with that filter")
        # instance type offering check
        try:
            ec2.describe_instance_type_offerings(
                Filters=[{"Name": "instance-type", "Values": ["t3.xlarge", "m6i.xlarge"]}])
            print("  instance types queryable: OK")
        except ClientError as e:
            print(f"  instance type offering: {e.response['Error']['Code']}")
    except EndpointConnectionError as e:
        print(f"  EC2 endpoint UNREACHABLE: {e}")
    except ClientError as e:
        print(f"  EC2 ClientError: {e.response['Error']['Code']} - {e.response['Error']['Message'][:120]}")
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")


print("account probe via STS:")
try:
    ident = boto3.client("sts").get_caller_identity()
    print(f"  account={ident['Account']} arn={ident['Arn']}")
except Exception as e:
    print(f"  STS failed: {e}")

for r in REGIONS:
    probe(r)
