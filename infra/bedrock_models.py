"""List Claude models visible to Bedrock from wherever this runs (EC2). Confirms the
Bedrock reader can work here."""
import os
import boto3

region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
try:
    c = boto3.client("bedrock", region_name=region)
    ms = c.list_foundation_models()
    ids = [m["modelId"] for m in ms["modelSummaries"]
           if "claude" in m["modelId"].lower()]
    print("BEDROCK_OK region=" + region + " claude_models=" + str(len(ids)))
    for x in ids[:12]:
        print("  " + x)
except Exception as e:
    print("BEDROCK_FAIL: " + type(e).__name__ + ": " + str(e)[:200])
