"""Provision the LASTWORD EC2 node (idempotent). us-east-1 by default.

Creates (reusing if present, all tagged Project=lastword):
  - key pair 'lastword-key' -> saves infra/lastword-key.pem (gitignored)
  - security group 'lastword-sg' in the default VPC: SSH 22 + WireGuard UDP 51820
    from THIS machine's public IP only
  - one Ubuntu 24.04 instance (default t3.xlarge: 4 vCPU/16GB), 200GB gp3, cloud-init

Prints the instance id + public IP + the ssh command. Does NOT auto-terminate.
Teardown: python infra/provision_ec2.py --terminate
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
AMI = {"us-east-1": "ami-0fa5967347d08d2df", "us-west-2": "ami-03d70b8354a16a8bc"}
KEY_NAME = "lastword-key"
SG_NAME = "lastword-sg"
TAG = [{"Key": "Project", "Value": "lastword"}]
PEM_PATH = os.path.join(ROOT, "infra", f"{KEY_NAME}.pem")


def my_ip() -> str:
    import urllib.request
    return urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10).read().decode().strip()


def ensure_key(ec2):
    try:
        ec2.describe_key_pairs(KeyNames=[KEY_NAME])
        print(f"key pair {KEY_NAME}: exists (reusing; pem must already be at {PEM_PATH})")
        return
    except ClientError:
        pass
    kp = ec2.create_key_pair(KeyName=KEY_NAME,
                             TagSpecifications=[{"ResourceType": "key-pair", "Tags": TAG}])
    with open(PEM_PATH, "w") as f:
        f.write(kp["KeyMaterial"])
    try:
        os.chmod(PEM_PATH, 0o600)
    except Exception:
        pass
    print(f"key pair {KEY_NAME}: created, private key saved to {PEM_PATH}")


def default_vpc(ec2) -> str:
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    return vpcs[0]["VpcId"]


def ensure_sg(ec2, vpc_id, ip) -> str:
    sgs = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SG_NAME]},
                 {"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
    if sgs:
        sg_id = sgs[0]["GroupId"]
        print(f"security group {SG_NAME}: exists ({sg_id})")
    else:
        sg_id = ec2.create_security_group(
            GroupName=SG_NAME, Description="LASTWORD node (SSH + WireGuard)",
            VpcId=vpc_id,
            TagSpecifications=[{"ResourceType": "security-group", "Tags": TAG}])["GroupId"]
        print(f"security group {SG_NAME}: created ({sg_id})")
    cidr = f"{ip}/32"
    for proto, port in [("tcp", 22), ("udp", 51820)]:
        try:
            ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[{"IpProtocol": proto, "FromPort": port, "ToPort": port,
                                "IpRanges": [{"CidrIp": cidr, "Description": "lastword-dell"}]}])
            print(f"  allow {proto}/{port} from {cidr}")
        except ClientError as e:
            if "InvalidPermission.Duplicate" in str(e):
                print(f"  {proto}/{port} from {cidr} already allowed")
            else:
                raise
    return sg_id


def find_instance(ec2):
    r = ec2.describe_instances(
        Filters=[{"Name": "tag:Project", "Values": ["lastword"]},
                 {"Name": "instance-state-name", "Values": ["pending", "running", "stopped"]}])
    for res in r["Reservations"]:
        for inst in res["Instances"]:
            return inst
    return None


def launch(ec2, sg_id, instance_type):
    user_data = open(os.path.join(ROOT, "infra", "cloud-init.yaml")).read()
    r = ec2.run_instances(
        ImageId=AMI[REGION], InstanceType=instance_type, KeyName=KEY_NAME,
        MinCount=1, MaxCount=1, SecurityGroupIds=[sg_id],
        BlockDeviceMappings=[{"DeviceName": "/dev/sda1",
                              "Ebs": {"VolumeSize": 200, "VolumeType": "gp3"}}],
        UserData=base64.b64encode(user_data.encode()).decode(),
        TagSpecifications=[{"ResourceType": "instance",
                            "Tags": TAG + [{"Key": "Name", "Value": "lastword-node"}]}])
    return r["Instances"][0]["InstanceId"]


def terminate(ec2):
    inst = find_instance(ec2)
    if not inst:
        print("no lastword instance to terminate")
        return
    iid = inst["InstanceId"]
    ec2.terminate_instances(InstanceIds=[iid])
    print(f"terminating {iid} ...")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-type", default="t3.xlarge")
    ap.add_argument("--terminate", action="store_true")
    args = ap.parse_args()

    ec2 = boto3.client("ec2", region_name=REGION)
    print(f"region: {REGION}")

    if args.terminate:
        terminate(ec2)
        return

    existing = find_instance(ec2)
    if existing and existing["State"]["Name"] in ("pending", "running"):
        iid = existing["InstanceId"]
        print(f"instance already exists: {iid} ({existing['State']['Name']})")
    else:
        ip = my_ip()
        ensure_key(ec2)
        vpc = default_vpc(ec2)
        sg = ensure_sg(ec2, vpc, ip)
        iid = launch(ec2, sg, args.instance_type)
        print(f"launched {iid} ({args.instance_type}, 200GB gp3)")

    print("waiting for running + public IP ...")
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    desc = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
    pub = desc.get("PublicIpAddress", "(none)")
    print(f"\nINSTANCE  {iid}")
    print(f"PUBLIC_IP {pub}")
    print(f"SSH       ssh -i {PEM_PATH} ubuntu@{pub}")
    print("cloud-init (docker/avalanche-cli/wireguard) runs ~2-4 min; "
          "check: ssh ... 'ls CLOUD_INIT_DONE'")


if __name__ == "__main__":
    main()
