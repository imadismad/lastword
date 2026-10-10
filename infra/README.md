# infra — EC2 node + Avalanche L1 + WireGuard (the hybrid chain, §16bis/§16ter)

Stands up the cloud side of the hybrid PoC: an EC2 Linux node running the Avalanche L1
(Subnet-EVM) that the spec calls for, replacing anvil as the real chain. The Dell runs
the agent/bridge and reaches the L1 RPC over WireGuard.

## Provision the EC2 node

```
python infra/provision_ec2.py                 # launches t3.xlarge, Ubuntu 24.04, 200GB
python infra/provision_ec2.py --terminate     # tear down when done
```

- Region: us-east-1 (set `AWS_DEFAULT_REGION`; us-west-2 also allowed).
- Security group `lastword-sg`: SSH 22 + WireGuard UDP 51820 from THIS machine's public
  IP only. Key saved to `infra/lastword-key.pem` (gitignored).
- cloud-init (`cloud-init.yaml`) installs Docker, avalanche-cli, WireGuard, Foundry.
- EC2 endpoints are reachable from the Dell's network (unlike Bedrock); STS confirms the
  creds (account 651408235101, WSParticipantRole).

## Stand up the Avalanche L1 (runs on EC2)

```
scp ... genesis.json setup_avalanche.sh ubuntu@<ip>:/home/ubuntu/
ssh ... bash setup_avalanche.sh
```

`make_genesis.py` builds `genesis.json`: chainId 99999, Subnet-EVM upgrades active at
genesis (durango/etna), and the SAME well-known test accounts the contracts/bridge use
prefunded with 1,000,000 LWT each — so the L1 behaves exactly like the local anvil dev
chain. `setup_avalanche.sh` creates (non-interactive: `--sovereign=false --icm=false
--latest --evm-token LWT --genesis`) and deploys it locally on EC2.

### Live chain (last deploy)

```
Network      : lastword  (Subnet-EVM v0.8.0)
Chain ID     : 99999
BlockchainID : 2L6HsHiCxGeQFBoe5ezfz9ZBtNBZYGKC1QHrDCeQhLPYrW3iZj
RPC (on EC2) : http://127.0.0.1:9650/ext/bc/2L6HsHiCxGeQFBoe5ezfz9ZBtNBZYGKC1QHrDCeQhLPYrW3iZj/rpc
Prefunded    : anvil accounts 0-4 (deployer/agent/bridge/co-admin/guardian), 1,000,000 LWT each
```

The RPC listens on EC2 localhost. The Dell reaches it through the WireGuard tunnel
(sortant from the Dell, UDP 51820 open on the SG). The bridge then points
`LASTWORD_RPC_URL` at the tunnelled RPC.

## SSH without hangs

Windows OpenSSH can wedge a piped shell. Always use `-n` (stdin from NUL) + `BatchMode`:
`infra/ssh_ec2.ps1 -Cmd "<remote cmd>"` wraps this.

## Cost / teardown

t3.xlarge is a few $/day; the sandbox account is deleted at the end. Tear down early
with `python infra/provision_ec2.py --terminate` (or stop the instance) when not in use.
