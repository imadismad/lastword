import boto3, json, os
from dotenv import load_dotenv
load_dotenv()
ec2 = boto3.client("ec2", region_name="us-east-1")
r = ec2.describe_instances(InstanceIds=["i-06b1af13ef6af465a"])
inst = r["Reservations"][0]["Instances"][0]
print(json.dumps({
    "state": inst["State"]["Name"],
    "public_ip": inst.get("PublicIpAddress"),
    "launch": str(inst.get("LaunchTime")),
}, indent=2))
# Also check security group ingress for port 22
sg_ids = [g["GroupId"] for g in inst["SecurityGroups"]]
for sg in ec2.describe_security_groups(GroupIds=sg_ids)["SecurityGroups"]:
    for p in sg["IpPermissions"]:
        cidrs = [c["CidrIp"] for c in p.get("IpRanges", [])]
        print("ingress", p.get("FromPort"), "->", p.get("ToPort"), cidrs)
