"""LASTWORD AI agent: isolated reader + deterministic guard.

The agent decides whether to ASK, never whether to pay. Its only verdicts are
REJECT, ASK_DELIVERY, ASK_BADGE. It holds no key and no payment power. Every model
output is treated as data and validated against a strict JSON schema before use.
"""
__version__ = "1.0.0"
