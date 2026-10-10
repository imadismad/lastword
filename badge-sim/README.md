# badge-sim — software badge (stands in for the TROPIC01 firmware)

Implements the I3 serial protocol over TCP using the exact `lastword_proto` library,
so it is byte-compatible with the real `badge-fw`. Lets the bridge run end-to-end with
no hardware. When the firmware is ready it replaces this over the same I3 protocol.

```
python badge-sim/badge_sim.py --tcp 127.0.0.1:8766           # interactive PIN prompts
python badge-sim/badge_sim.py --tcp 127.0.0.1:8766 --auto    # auto-approve (CI/tests)
python badge-sim/badge_sim.py --print-pubkeys                # dump the 3 P-256 pubkeys
```

Three software P-256 keys: `stock`, `daf`, `duress` (deterministic from a seed, test
only). Default PINs: stock `1111`, DAF `2222`, duress `9999` (override via env
`PIN_STOCK` / `PIN_DAF` / `PIN_DURESS`). The duress PIN signs with the duress key and
produces an outwardly identical response frame.

**Gateway key:** the badge verifies the gateway signature on each request before
displaying anything. The gateway public key must match the bridge's gateway key — pass
it via env `GATEWAY_PUB` (hex, 64 bytes). The bridge exports it on startup.

Always shows a `[SOFTWARE KEY]` banner — the hardware guarantee is not demonstrated in
sim mode (declared, per cahier des charges §8 repli).
