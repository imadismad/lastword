"""Non-destructive probe of the LoRa nugget on COM6: open, read whatever it emits,
and show any human-readable banner. Does NOT write badge/mesh frames."""
import sys, time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

try:
    ser = serial.Serial(PORT, BAUD, timeout=1)
except Exception as e:
    print(f"OPEN_FAIL {PORT}: {e}")
    sys.exit(1)

print(f"OPEN_OK {PORT} @ {BAUD}")
# Nudge: many firmwares print a banner on a newline / Ctrl-C.
try:
    ser.reset_input_buffer()
    ser.write(b"\r\n")
    ser.flush()
except Exception as e:
    print(f"WRITE_WARN: {e}")

deadline = time.time() + 4
raw = bytearray()
while time.time() < deadline:
    chunk = ser.read(256)
    if chunk:
        raw += chunk
ser.close()

print(f"BYTES_READ={len(raw)}")
if raw:
    printable = bytes(b if 32 <= b < 127 or b in (10, 13) else 46 for b in raw[:400])
    print("ASCII:", printable.decode("ascii", "replace"))
    print("HEX  :", raw[:64].hex())
else:
    print("No spontaneous output (silent firmware or needs a specific protocol handshake).")
