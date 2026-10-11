# LASTWORD benchmark (spec section 14)

```powershell
.venv\Scripts\python.exe bench\dataset.py   # 300 normal + 60 attacks, fixed seed -> bench/data/dataset.jsonl
.venv\Scripts\python.exe bench\run.py       # ~2 min -> bench/results/report.md + results.json
```

Needs Foundry (`anvil`, `forge`). It deploys the real `LastWord` contract on a private
anvil chain (port 8547), runs the real agent code, and uses the software badge, which
speaks the same protocol as the TROPIC01 firmware. No AWS, no radio, no real data.

Layers measured separately:
- **Agent (as built)**: reader plus guard verdict and the warnings the badge displays.
- **Contract, as built**: only quotes the agent approves are proposed.
- **Contract alone**: every payable quote is proposed, as if the agent were compromised
  (spec test T-04).
- **Baselines**: R1, classic AP rules that pay the address on the invoice. R2, R1 plus
  the vendor-master address check. Both auto-pay, with no hardware approval.
- **Radio frames and the contract**: forged frames, rogue gateway, replays, parameters
  changed after signature, STOCK signature presented as DAF, approval after the deadline
  (spec tests T-02 and T-03).
- **Evidence journal**: entries modified, deleted or reordered (spec test T-07).
