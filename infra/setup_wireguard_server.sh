#!/usr/bin/env bash
# Runs ON EC2. WireGuard server (wg0) + socat forward of the L1 RPC onto the tunnel.
# Prints the server public key and the client private key for the Dell. Idempotent.
set -uo pipefail
WG=/etc/wireguard

gen() { sudo bash -c "umask 077; wg genkey | tee $1" | wg pubkey | sudo tee ${1%.key}_pub.key >/dev/null; }

if ! sudo test -f $WG/server.key; then
  sudo bash -c "umask 077; wg genkey | tee $WG/server.key | wg pubkey > $WG/server_pub.key"
fi
if ! sudo test -f $WG/client.key; then
  sudo bash -c "umask 077; wg genkey | tee $WG/client.key | wg pubkey > $WG/client_pub.key"
fi

SERVER_PRIV=$(sudo cat $WG/server.key)
SERVER_PUB=$(sudo cat $WG/server_pub.key)
CLIENT_PRIV=$(sudo cat $WG/client.key)
CLIENT_PUB=$(sudo cat $WG/client_pub.key)

sudo bash -c "cat > $WG/wg0.conf" <<EOF
[Interface]
Address = 10.9.0.1/24
ListenPort = 51820
PrivateKey = $SERVER_PRIV

[Peer]
PublicKey = $CLIENT_PUB
AllowedIPs = 10.9.0.2/32
EOF

sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null
sudo wg-quick down wg0 >/dev/null 2>&1 || true
sudo wg-quick up wg0

# socat: expose the L1 RPC (loopback-only) on the WG interface for the Dell
sudo apt-get install -y socat >/dev/null 2>&1 || true
sudo pkill -f "socat.*9650" >/dev/null 2>&1 || true
sudo bash -c 'nohup socat TCP-LISTEN:9650,bind=10.9.0.1,fork,reuseaddr TCP:127.0.0.1:9650 >/var/log/socat9650.log 2>&1 &'
sleep 1

echo "WG_SERVER_PUBLIC_KEY=$SERVER_PUB"
echo "WG_CLIENT_PRIVATE_KEY=$CLIENT_PRIV"
echo "WG_STATUS:"; sudo wg show
echo "SOCAT:"; sudo ss -ltn 2>/dev/null | grep 9650 || echo "see /var/log/socat9650.log"
echo "ALL_DONE"
