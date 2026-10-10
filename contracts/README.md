# contracts — LASTWORD smart contract (Foundry)

The contract is the only payment authority (cahier des charges §6, §10, §11).
Three steps, three distinct signatures, hard criteria enforced on-chain.

## Dependencies (not committed — reinstall with forge)

```
forge install foundry-rs/forge-std --no-git
forge install OpenZeppelin/openzeppelin-contracts --no-git   # v5.7.0, provides P256.verify
```

`P256.verify(h, r, s, qx, qy)` tries the secp256r1 precompile at `0x100` (ACP-204 /
Granite) and falls back to the Solidity implementation. The digest `h` is the
SHA-256 defined in `proto/SPEC.md` (I1), recomputed on-chain, never trusted from input.

## Build & test

```
forge build
forge test            # 14 tests, all green
```

Tests cover: nominal payment, forged/wrong-key signature, tampered digest, replayed
nonce, expired deadline, role separation (stock sig cannot approve), approval without
attestation, high-s rejected (T-01), duress → capped parallel vault with identical
event, hard criteria (whitelist C1, cap C3, duplicate C6, token C9), pause/unpause
authorization, whitelist timelock + double-sign (FR-04).

## Deploy

```
forge script script/Deploy.s.sol --rpc-url <RPC> --broadcast
```
See `Deploy.s.sol` for required env vars (deployer key, role addresses, badge pubkeys
from badge_pubkeys.json). The badge pubkeys are the three P-256 keys: stock, DAF, duress.

## Key invariant

The low-s requirement: OpenZeppelin's `P256` rejects a high `s`. The bridge (or badge)
must normalize `s := n - s if s > n/2` before calling `approve`/`attestDelivery`.
`lastword_proto.normalize_s` does this; the contract test proves high-s is rejected.
