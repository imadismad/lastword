"""badge-sim — software badge implementing I3 over TCP (and framed stdin optional).

Mirrors the real cdc-badge-os LASTWORD module so the bridge can run end-to-end with
no hardware. Holds three software P-256 keys (stock, DAF, duress), decrypts the I2
request frame, recomputes the digest, shows the role + fields, asks for a PIN, signs,
and returns the I2 response. Byte-compatible with the firmware because it uses the
exact same lastword_proto library.

Run:
    python badge-sim/badge_sim.py --tcp 127.0.0.1:8766            # interactive PINs
    python badge-sim/badge_sim.py --tcp 127.0.0.1:8766 --auto     # auto-approve (tests)

Protocol (I3): COBS frames carrying  cmd(1) | len(2) | data | crc16(2).
  HELLO     -> HELLO_OK(stock_pub||daf_pub||duress_pub)   (3 x 64 bytes)
  PROVISION(frameKey32||chainId8||contractAddr20||gatewayPub64) -> PROV_OK
  REQUEST(I2 request frame) -> RESPONSE(I2 response frame) | REFUSED(code)
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading

# allow running from repo without install
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "proto", "src"))

from cryptography.hazmat.primitives.asymmetric import ec

from lastword_proto import (
    Intent, Role, digest as compute_digest,
    pub_to_bytes, sign_digest, verify_digest, normalize_s,
    open_frame, parse_request_body, build_response_frame,
    pack_message, unpack_message, Command, RefuseReason,
)
from lastword_proto.crypto import sig_to_bytes, sig_from_bytes, FrameHeader, TYPE_REQUEST

# Deterministic software keys (test only) unless overridden by env PINs.
import hashlib
SEED = os.environ.get("BADGE_SIM_SEED", "lastword-badge-sim-v1").encode()


def _deriv(label: str) -> ec.EllipticCurvePrivateKey:
    from lastword_proto.crypto import P256_N
    h = int.from_bytes(hashlib.sha256(SEED + b"|" + label.encode()).digest(), "big")
    return ec.derive_private_key((h % (P256_N - 1)) + 1, ec.SECP256R1())


class BadgeSim:
    ROLE_LABELS = {Role.STOCK: "RESPONSABLE STOCK (simule)", Role.DAF: "DAF (simule)"}

    # PINs per role (demo). The duress PIN maps to the duress key.
    PINS = {
        "stock": os.environ.get("PIN_STOCK", "1111"),
        "daf": os.environ.get("PIN_DAF", "2222"),
        "duress": os.environ.get("PIN_DURESS", "9999"),
    }

    def __init__(self, auto: bool = False, software_banner: bool = True):
        self.auto = auto
        self.software_banner = software_banner
        self.keys = {
            "stock": _deriv("stock"),
            "daf": _deriv("daf"),
            "duress": _deriv("duress"),
        }
        self.frame_key: bytes | None = None
        self.chain_id: int | None = None
        self.contract_addr: bytes | None = None
        self.gateway_pub: bytes | None = None
        self.counter = 1000  # response frame counter

    def pubkeys_blob(self) -> bytes:
        return (pub_to_bytes(self.keys["stock"].public_key())
                + pub_to_bytes(self.keys["daf"].public_key())
                + pub_to_bytes(self.keys["duress"].public_key()))

    # ---- command handlers -> return a framed response message ----
    def handle(self, framed: bytes) -> bytes:
        try:
            cmd, data = unpack_message(framed)
        except ValueError:
            return pack_message(Command.REFUSED, bytes([RefuseReason.BAD_AEAD]))

        if cmd == Command.HELLO:
            return pack_message(Command.HELLO_OK, self.pubkeys_blob())

        if cmd == Command.PROVISION:
            # frameKey(32) || chainId(8) || contractAddr(20) || gatewayPub(64) = 124
            if len(data) != 124:
                return pack_message(Command.REFUSED, bytes([RefuseReason.OTHER]))
            self.frame_key = data[:32]
            self.chain_id = int.from_bytes(data[32:40], "big")
            self.contract_addr = data[40:60]
            self.gateway_pub = data[60:124]  # installed gateway pubkey (X||Y)
            print(f"[badge] provisioned: chainId={self.chain_id} "
                  f"contract=0x{self.contract_addr.hex()}")
            return pack_message(Command.PROV_OK)

        if cmd == Command.REQUEST:
            return self._handle_request(data)

        return pack_message(Command.REFUSED, bytes([RefuseReason.OTHER]))

    def _handle_request(self, frame: bytes) -> bytes:
        if self.frame_key is None:
            return pack_message(Command.REFUSED, bytes([RefuseReason.NOT_PROVISIONED]))
        # 1. decrypt + verify AEAD/counter
        try:
            hdr, pt = open_frame(self.frame_key, frame)
        except Exception:
            return pack_message(Command.REFUSED, bytes([RefuseReason.BAD_AEAD]))
        if hdr.type != TYPE_REQUEST:
            return pack_message(Command.REFUSED, bytes([RefuseReason.BAD_AEAD]))
        try:
            intent_bytes, gateway_sig = parse_request_body(pt)
        except ValueError:
            return pack_message(Command.REFUSED, bytes([RefuseReason.BAD_AEAD]))

        # 2. recompute digest from the DECODED fields (never trust free text)
        intent = Intent.decode(intent_bytes)
        dg = compute_digest(intent, self.chain_id, self.contract_addr)

        # 3. verify the gateway signature over the digest BEFORE displaying anything.
        #    Prefer the gateway pubkey installed by PROVISION; fall back to the
        #    seed-derived one for older flows/tests.
        from lastword_proto import pub_from_bytes
        gq = pub_from_bytes(self.gateway_pub) if getattr(self, "gateway_pub", None) else _gateway_pub()
        gr, gs = sig_from_bytes(gateway_sig)
        if not verify_digest(gq, dg, gr, gs):
            print("[badge] gateway signature INVALID - ignoring request")
            return pack_message(Command.REFUSED, bytes([RefuseReason.BAD_GATEWAY_SIG]))

        role = intent.role
        role_label = self.ROLE_LABELS.get(role, f"ROLE?{int(role)}")

        # 4. display the recomputed fields (what we sign), ask for PIN
        self._show(intent, role_label)
        pin = self._get_pin(role)
        if pin is None:
            return pack_message(Command.REFUSED, bytes([RefuseReason.USER_REFUSED]))

        signer_name = self._key_for_pin(role, pin)
        if signer_name is None:
            print("[badge] wrong PIN")
            return pack_message(Command.REFUSED, bytes([RefuseReason.USER_REFUSED]))

        # 5. sign the digest with the role's key; normalize s (badge or bridge may do it)
        r, s = sign_digest(self.keys[signer_name], dg, low_s=False)
        s = normalize_s(s)
        badge_sig = sig_to_bytes(r, s)

        self.counter += 1
        resp = build_response_frame(self.frame_key, hdr.badgeId, self.counter,
                                    intent.reqId, decision=1, badge_sig=badge_sig)
        print(f"[badge] signed reqId={intent.reqId} with '{signer_name}' key -> APPROVED")
        return pack_message(Command.RESPONSE, resp)

    def _show(self, intent: Intent, role_label: str):
        banner = "  [SOFTWARE KEY - hardware guarantee NOT demonstrated]" if self.software_banner else ""
        print("\n" + "=" * 56)
        print(f"  ROLE : {role_label}{banner}")
        print(f"  beneficiary : 0x{intent.beneficiary.hex()[:6]}...{intent.beneficiary.hex()[-4:]}")
        print(f"  amount      : {intent.amount} (token #{intent.token})")
        print(f"  deadline    : {intent.deadline}")
        print(f"  reqId       : {intent.reqId}   nonce : {intent.nonce}")
        print(f"  flags       : 0x{intent.flags:04x}   policy : {intent.policy}")
        print("=" * 56)

    def _get_pin(self, role: Role) -> str | None:
        if self.auto:
            name = "stock" if role == Role.STOCK else "daf"
            return self.PINS[name]
        try:
            ans = input("  Approve? type PIN (or 'n' to refuse): ").strip()
        except EOFError:
            return None
        if ans.lower() in ("n", "no", ""):
            return None
        return ans

    def _key_for_pin(self, role: Role, pin: str) -> str | None:
        if role == Role.STOCK:
            return "stock" if pin == self.PINS["stock"] else None
        if role == Role.DAF:
            if pin == self.PINS["daf"]:
                return "daf"
            if pin == self.PINS["duress"]:
                return "duress"   # duress key, identical outward behaviour
            return None
        return None


# gateway pubkey must match what the bridge signs with. The bridge/badge share the
# same test gateway key derived from the proto seed in vectors; for the sim we derive
# it from the badge seed-independent gateway label used by the bridge.
_GATEWAY_PUB_CACHE = None


def _gateway_pub():
    global _GATEWAY_PUB_CACHE
    if _GATEWAY_PUB_CACHE is None:
        from lastword_proto import pub_from_bytes
        hexpub = os.environ.get("GATEWAY_PUB")
        if hexpub:
            _GATEWAY_PUB_CACHE = pub_from_bytes(bytes.fromhex(hexpub))
        else:
            # default: derive the same way the bridge does
            _GATEWAY_PUB_CACHE = _deriv("gateway").public_key()
    return _GATEWAY_PUB_CACHE


# ------------------------------------------------------------------ TCP server
def read_cobs_frame(sock: socket.socket) -> bytes | None:
    """Read bytes until a 0x00 delimiter; return the frame incl. delimiter."""
    buf = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            return None
        buf += b
        if b == b"\x00":
            return bytes(buf)


def serve_tcp(host: str, port: int, badge: BadgeSim):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(5)
    print(f"[badge] listening on tcp://{host}:{port} (auto={badge.auto})")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle_conn, args=(conn, badge), daemon=True).start()


def _handle_conn(conn: socket.socket, badge: BadgeSim):
    with conn:
        while True:
            frame = read_cobs_frame(conn)
            if frame is None:
                return
            resp = badge.handle(frame)
            conn.sendall(resp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcp", default="127.0.0.1:8766", help="host:port to listen on")
    ap.add_argument("--auto", action="store_true", help="auto-approve with role PIN")
    ap.add_argument("--print-pubkeys", action="store_true",
                    help="print the 3 pubkeys as JSON and exit")
    args = ap.parse_args()

    badge = BadgeSim(auto=args.auto)

    if args.print_pubkeys:
        import json
        print(json.dumps({
            "stock": pub_to_bytes(badge.keys["stock"].public_key()).hex(),
            "daf": pub_to_bytes(badge.keys["daf"].public_key()).hex(),
            "duress": pub_to_bytes(badge.keys["duress"].public_key()).hex(),
        }, indent=2))
        return

    host, port = args.tcp.split(":")
    serve_tcp(host, int(port), badge)


if __name__ == "__main__":
    main()
