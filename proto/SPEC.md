# LASTWORD — Frozen interface spec (proto v1)

> **Rule.** This file and `vectors.json` are frozen. No component invents a format.
> A format change requires agreement of both engineers (I and N), a version bump,
> and regenerated vectors. Every component ships a test that replays `vectors.json`.

This spec consolidates §7, §16bis and §16quater of the cahier des charges into the
six interfaces I1–I6. Everything is little-endian unless stated; multi-byte integers
in the intention are **big-endian** (network order) to match how the contract reads
them.

---

## I1 — Payment intent (79 bytes, canonical)

The intent is the structure whose hash is signed by the badge and recomputed by the
contract. Exactly **79 bytes**, fields in this fixed order:

| # | Field          | Bytes | Type        | Meaning |
|---|----------------|-------|-------------|---------|
| 1 | version        | 1     | u8          | format version, = `1` |
| 2 | algorithm      | 1     | u8          | `1` = ECDSA P-256; other values reserved (hybrid) |
| 3 | reqId          | 4     | u32 BE      | unique request id |
| 4 | beneficiary    | 20    | bytes       | supplier EVM address |
| 5 | token          | 1     | u8          | index into the allowed-token list |
| 6 | amount         | 8     | u64 BE      | smallest unit of the token |
| 7 | nonce          | 4     | u32 BE      | approver counter |
| 8 | deadline       | 4     | u32 BE      | unix timestamp (seconds) |
| 9 | quoteHash      | 32    | bytes       | sha256 of the source quote, binds decision to document |
| 10| flags          | 2     | u16 BE      | verdict reasons + role (see below) |
| 11| policy         | 2     | u16 BE      | version of the pre-validation criteria applied |

Total: 1+1+4+20+1+8+4+4+32+2+2 = **79**.

### flags (u16, bit layout)

Bits 0–1 encode the **role** (this is part of what is signed, so a "stock" signature
can never be replayed as a "DAF" approval):

| bits 0–1 | role       |
|----------|------------|
| `00`     | unset / invalid |
| `01`     | stock (delivery attestation) |
| `10`     | DAF (payment approval) |
| `11`     | reserved |

Remaining bits are verdict-reason indicators (OR-able):

| bit | reason |
|-----|--------|
| 2   | new beneficiary |
| 3   | external origin |
| 4   | atypical amount |
| 5   | injection suspected |
| 6   | address changed |
| 7   | duress (internal-only; NEVER set in a frame or event — see §11) |

> Note: the duress bit exists in the proto model for completeness but the on-wire
> frame and the on-chain event must look identical for normal and duress approvals.
> The duress path is distinguished by *which key signed*, never by a visible flag.

### Digest (what is signed)

```
digest = SHA-256( "LASTWORD-v1" || chainId(8 bytes BE) || contractAddr(20 bytes) || intent(79 bytes) )
```

- `"LASTWORD-v1"` is the 11 ASCII bytes `4C 41 53 54 57 4F 52 44 2D 76 31` (domain tag).
- `chainId` is 8 bytes big-endian.
- `contractAddr` is the 20-byte contract address.
- The contract recomputes this digest from the parameters it executes; one byte of
  difference invalidates the signature.
- The digest is a **SHA-256**, not keccak. TROPIC01 signs a 256-bit hash; the
  OpenZeppelin `P256.verify` is fed this SHA-256 digest.

### Signature form

ECDSA P-256 produces `(r, s)`, 32 bytes each, 64 bytes total as `r || s`.
OpenZeppelin's `P256` library rejects a **high `s`**. The signer (badge) may emit a
random `s`; the **bridge normalizes** to low-s (`s := n - s if s > n/2`) before
calling the contract. `n` is the P-256 curve order:
`0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551`.

---

## I2 — Radio frame (end-to-end bridge <-> badge; Meshtastic and HP never read it)

Clear header + AES-256-GCM sealed body. The LoRa/Meshtastic layer and the HP
junction only move these bytes; they cannot read or forge them.

### Clear header (13 bytes)

| # | Field       | Bytes | Meaning |
|---|-------------|-------|---------|
| 1 | magic       | 2     | `0x4C 0x57` ("LW") |
| 2 | version     | 1     | = `1` |
| 3 | type        | 1     | `0x01` request, `0x02` response |
| 4 | badgeId     | 4     | u32 BE badge/pairing id |
| 5 | counter     | 4     | u32 BE strictly-increasing frame counter (anti-replay + GCM nonce source) |
| 6 | bodyLen     | 1     | u8 length of ciphertext (excl. tag) |

### AEAD

- Cipher: **AES-256-GCM**.
- Key: per-message key via **HKDF-SHA256** from the shared frame key installed at
  enrollment. `salt = ""`, `info = magic||version||type||badgeId||counter` (the 13-byte
  header), output 32 bytes.
- GCM nonce (12 bytes): `0x00 00 00 00 || type(1) || counter(4) || 0x00 00 00` —
  deterministic, unique per (type, counter). (A fixed scheme is fine because the
  per-message HKDF key already makes (key, nonce) unique.)
- AAD: the 13-byte clear header.
- Tag: 16 bytes, appended after ciphertext.

### Request body (type 0x01), plaintext before sealing — ~165 B frame total

| # | Field              | Bytes | Meaning |
|---|--------------------|-------|---------|
| 1 | intent             | 79    | I1 |
| 2 | gatewaySig         | 64    | P-256 sig of the gateway over `digest` (badge verifies before display) |

Sealed frame ≈ 13 (header) + 143 (ct) + 16 (tag) = **172 bytes** (fits a LoRa frame).

### Response body (type 0x02), plaintext before sealing — ~91 B frame total

| # | Field       | Bytes | Meaning |
|---|-------------|-------|---------|
| 1 | reqId       | 4     | echoes the request |
| 2 | decision    | 1     | `0x01` approve, `0x00` refuse |
| 3 | badgeSig    | 64    | P-256 sig of the badge over `digest` (the only truth the contract trusts) |

Sealed frame ≈ 13 + 69 + 16 = **98 bytes**. The response carries **no key id**: a
normal-key and a duress-key signature produce frames of identical shape and size.

---

## I3 — Badge serial link (junction/bridge <-> badge, and <-> badge-sim)

COBS-framed messages over the badge USB-CDC serial line. Each decoded message:

```
command (1 byte) | length (2 bytes BE) | data (length bytes) | CRC-16/CCITT-FALSE (2 bytes BE)
```

CRC-16/CCITT-FALSE: poly `0x1021`, init `0xFFFF`, no reflection, no final xor, over
`command||length||data`.

The whole message is then **COBS-encoded** and terminated by a `0x00` delimiter.

### Commands

| Code | Name     | Direction | data |
|------|----------|-----------|------|
| 0x01 | HELLO    | host->badge | (empty) |
| 0x81 | HELLO_OK | badge->host | 3 × 64-byte pubkeys: stock(64) \|\| daf(64) \|\| duress(64) (uncompressed X\|\|Y) |
| 0x02 | PROVISION| host->badge | frameKey(32) \|\| chainId(8 BE) \|\| contractAddr(20) \|\| gatewayPub(64, X\|\|Y) |
| 0x82 | PROV_OK  | badge->host | (empty) |
| 0x03 | REQUEST  | host->badge | an I2 request frame (type 0x01) |
| 0x83 | RESPONSE | badge->host | an I2 response frame (type 0x02) |
| 0x84 | REFUSED  | badge->host | reason code (1 byte) |

Refusal reason codes: `0x01` bad gateway sig, `0x02` bad AEAD/counter, `0x03` user
refused, `0x04` expired, `0x05` not provisioned, `0xFF` other.

> PROVISION gives the badge the frame key, chainId, contract address, and the
> gateway public key it needs to decrypt frames, recompute the digest it displays
> and signs, and verify the gateway's request signature before showing anything.
> Total payload: 32 + 8 + 20 + 64 = 124 bytes.

---

## I4 — Bridge local API (agent <-> bridge)

HTTP, listens **only** on the Dell's WSL interface. The agent reaches it through this
single local entry point and can send nothing else.

### `POST /proposals`

Strict JSON (unknown fields rejected). This is a *proposal*, never a command:

```json
{
  "supplier_id": "string",
  "beneficiary": "0x...20 bytes hex...",
  "token": 0,
  "amount": "123456",
  "deadline": 1760000000,
  "quote_hash": "0x...32 bytes hex...",
  "verdict": "ASK_BADGE",
  "criteria": { "whitelist": true, "cap": true, "duplicate": false, "...": true },
  "flags": 12,
  "policy": 1
}
```

`verdict` ∈ `REJECT | ASK_DELIVERY | ASK_BADGE`. Response:

```json
{ "reqId": 1234, "status": "received" }
```

### `GET /proposals/{reqId}`

```json
{ "reqId": 1234, "status": "received|sent|attested|approved|refused|expired" }
```

Only statuses are ever returned to the agent — never raw frames, keys or radio data.

---

## I5 — Contract ABI (bridge/witness <-> contract)

```
function propose(bytes intent, bytes proofs) returns (uint32 reqId)
function attestDelivery(uint32 reqId, bytes32 r, bytes32 s)
function approve(uint32 reqId, bytes32 r, bytes32 s)
function cancel(uint32 reqId)
function pause()
function unpause()
function anchor(bytes32 root)
function updateWhitelist(address supplier, uint256 cap, bool active) // timelocked

event Proposed(uint32 indexed reqId, bytes32 digest);
event Attested(uint32 indexed reqId);
event Approved(uint32 indexed reqId, address beneficiary, uint256 amount);
event Refused(uint32 indexed reqId, uint8 reason);
event Anchored(bytes32 root);
event Paused();
event Unpaused();
```

- `attestDelivery` requires the **stock** key signature (role bits `01`), state = proposed.
- `approve` requires the **DAF** key signature (role bits `10`), state = attested,
  within deadline, nonce fresh. The contract recomputes the digest and verifies the
  P-256 signature against the registered DAF (and duress) pubkeys.
- The digest is the SHA-256 defined in I1 — recomputed, never trusted from input.

---

## I6 — Test vectors (`vectors.json`, everyone)

Generated by `proto` with a **fixed seed**. Contains:

- test P-256 keys (stock, DAF, duress) — test only, published, never real.
- sample intents (bytes + decoded fields) and their digests.
- signatures in **both low-s and high-s** form.
- sealed I2 frames (request and response) with their frame key.
- COBS-framed I3 messages.
- invalid cases: wrong magic, bad tag, replayed counter, expired deadline, swapped
  role, high-s rejected-by-contract.

Each component has a test that reads `vectors.json` and checks it agrees byte-for-byte.
