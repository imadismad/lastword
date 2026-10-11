"""Emit a minimal EC2 env file with ONLY the AWS creds + region + a Bedrock model id,
read from the Dell's .env. Written to infra/bedrock.env (gitignored). Values are not printed.
"""
import os
from dotenv import load_dotenv

load_dotenv()
keys = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
# Use a cross-region inference-profile id (us.*) — base model ids reject on-demand converse.
model = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bedrock.env")
missing = [k for k in keys if not os.environ.get(k)]
with open(out, "w", encoding="utf-8", newline="\n") as f:
    for k in keys:
        f.write(f"{k}={os.environ.get(k, '')}\n")
    f.write(f"AWS_DEFAULT_REGION={region}\n")
    f.write(f"BEDROCK_MODEL_ID={model}\n")
print("wrote", out, "| missing:", missing or "none")
