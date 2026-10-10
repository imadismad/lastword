"""Probe AWS Bedrock access: identity, available models, and a tiny Converse call.

Reads creds from the repo .env (gitignored). Tries us-east-1 and us-west-2.
Prints a summary and, if a Converse call succeeds, the model id that worked.

Usage:  python agent/bedrock_probe.py
"""
from __future__ import annotations

import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

# load .env from repo root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

REGIONS = ["us-east-1", "us-west-2"]

# Candidate models to try for the isolated reader (lightweight, tool-capable).
# We try inference-profile ids (cross-region) first, then direct ids.
CANDIDATES = [
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "us.anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-5-haiku-20241022-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-micro-v1:0",
]


def who_am_i():
    try:
        sts = boto3.client("sts")
        ident = sts.get_caller_identity()
        print(f"[sts] account={ident['Account']} arn={ident['Arn']}")
    except Exception as e:
        print(f"[sts] FAILED: {e}")


def list_models(region: str) -> set[str]:
    ids: set[str] = set()
    try:
        br = boto3.client("bedrock", region_name=region)
        resp = br.list_foundation_models()
        for m in resp.get("modelSummaries", []):
            ids.add(m["modelId"])
        print(f"[{region}] {len(ids)} foundation models visible")
        # also inference profiles (cross-region)
        try:
            profs = br.list_inference_profiles().get("inferenceProfileSummaries", [])
            for p in profs:
                ids.add(p["inferenceProfileId"])
            print(f"[{region}] {len(profs)} inference profiles visible")
        except Exception as e:
            print(f"[{region}] inference profiles not listable: {e}")
    except ClientError as e:
        print(f"[{region}] list_foundation_models FAILED: {e.response['Error']['Code']}")
    except EndpointConnectionError as e:
        print(f"[{region}] endpoint error: {e}")
    return ids


def try_converse(region: str, model_id: str) -> bool:
    try:
        rt = boto3.client("bedrock-runtime", region_name=region,
                          config=Config(retries={"max_attempts": 1}))
        resp = rt.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "Reply with the single word OK."}]}],
            inferenceConfig={"maxTokens": 10, "temperature": 0},
        )
        text = resp["output"]["message"]["content"][0]["text"].strip()
        print(f"[{region}] CONVERSE OK via {model_id} -> {text!r}")
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"[{region}] converse {model_id}: {code}")
        return False
    except Exception as e:
        print(f"[{region}] converse {model_id}: {type(e).__name__} {e}")
        return False


def main():
    print("=== Bedrock probe ===")
    print(f"default region env: {os.environ.get('AWS_DEFAULT_REGION')}")
    who_am_i()

    working = []
    for region in REGIONS:
        print(f"\n--- {region} ---")
        visible = list_models(region)
        # Try candidates; prefer ones that appear in the visible set, but still
        # attempt the rest (list perms and invoke perms can differ).
        ordered = [c for c in CANDIDATES if c in visible] + \
                  [c for c in CANDIDATES if c not in visible]
        for cand in ordered:
            if try_converse(region, cand):
                working.append((region, cand))
                break  # one working model per region is enough

    print("\n=== RESULT ===")
    if working:
        for region, model in working:
            print(f"WORKS: region={region} model={model}")
        r, m = working[0]
        print(f"\nRECOMMEND: AWS_DEFAULT_REGION={r}  BEDROCK_MODEL_ID={m}")
    else:
        print("No Converse call succeeded. Check model access in the Bedrock console")
        print("(model access must be granted) or whether the creds have bedrock perms.")
        sys.exit(1)


if __name__ == "__main__":
    main()
