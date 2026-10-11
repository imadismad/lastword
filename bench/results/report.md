# LASTWORD benchmark

Synthetic, reproducible dataset (seed fixed, no real data): **300 normal payments** and **60 attacks** (10 per type). Real `LastWord` contract on a local chain, real agent code, software badge speaking the same protocol as the TROPIC01 firmware.

## Headline

- Funds payable to an attacker-controlled wallet: **0**, even with the agent assumed compromised (the contract only pays whitelisted addresses). Rules-only automation auto-pays **40 of 60** attacks (16,247 dUSD, of which 9,659 dUSD to attacker wallets).
- Payments executed without a human PIN on the hardware badge: **0** (LASTWORD) vs every rule-passing invoice (baselines).
- Agent detection (stop or visible warning): recall **75.0 %**, precision **69.2%**, false rejects **0.0%**, false warnings **6.7%**.
- Detection delay (quote -> verdict): median **0.09 ms**, p95 0.15 ms (local reader).

## Per attack type

| Attack (10 each) | Agent rejects | Agent alerts | Stopped before badge | Contract alone stops (agent compromised) | Reaches badge with warning | Reaches badge silently | Rules-only (R1) auto-pays | Strong rules (R2) auto-pays |
|---|---|---|---|---|---|---|---|---|
| address_swap | 10 | 10 | 10 | 10 | 0 | 0 | 10 | 0 |
| duplicate_split | 0 | 5 | 5 | 5 | 5 | 0 | 5 | 5 |
| expired_replay | 0 | 0 | 5 | 5 | 0 | 5 | 5 | 5 |
| fake_urgency | 10 | 10 | 10 | 10 | 0 | 0 | 10 | 0 |
| injection | 5 | 10 | 5 | 5 | 5 | 0 | 10 | 5 |
| not_whitelisted | 10 | 10 | 10 | 10 | 0 | 0 | 0 | 0 |

R1 = classic AP rules (known vendor, under cap, new invoice number) paying the address on the invoice. R2 = R1 + payout address must match the vendor master. Both pay automatically, with no hardware approval.

## Radio frames and contract enforcement (T-02, T-03)

| Test (50 each) | Result |
|---|---|
| forged_frame | 50 refused |
| rogue_gateway_frame | 50 refused |
| replayed_frame_at_badge | 50 re-displayed & signed |
| param_changed_after_signature | 50 refused (C7) |
| stock_sig_as_daf | 50 refused (BadSignature) |
| approval_replayed_on_chain | 50 refused (BadState) |
| approved_after_deadline | 50 refused (C8) |

## Evidence journal tampering (T-07)

| Tamper (50 each) | Result |
|---|---|
| modify | 50 detected, 50 first bad entry located |
| delete | 50 detected, 50 first bad entry located |
| reorder | 50 detected, 50 first bad entry located |

## Normal traffic

- 300 of 300 legitimate payments reach the badge for approval.
- False rejects (legit payment blocked by the agent): 0 shown below (first 20).


## Not measured here

- Bedrock Guardrails baseline (needs AWS credentials; not run).
- LoRa range, live airtime and gas: measured on the hardware/L1 separately (6.1 s airtime, 328k gas per payment).
