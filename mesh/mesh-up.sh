#!/bin/bash
# hark-vm reciprocal SSH endpoint (Owner ruling 2026-11-26: all mesh nodes reciprocal).
# Self-bootstrapping: userspace OpenSSH sshd on 127.0.0.1:2222 (key-only) + Pinggy reverse tcp tunnel.
# Re-run per Hark session: sandbox resets wipe /workspace/work; this script re-extracts binaries,
# re-mints keys when absent, and prints ENDPOINT + CLIENT_PUB for hark/comms.jsonl.
# Peers: pass pubkey lines via MESH_PEER_KEYS (newline-separated).
# Usage: curl -sfL <raw url> | bash -s -- [hold_seconds]   (default 1100; NO_WAIT=1 to return after ENDPOINT)
D=${MESH_DIR:-/tmp/mesh-sshd}; R=$D/root; mkdir -p $D/deb $R; cd $D || exit 1
export LD_LIBRARY_PATH=$R/usr/lib/aarch64-linux-gnu:$R/usr/lib/x86_64-linux-gnu
if [ ! -x $R/usr/sbin/sshd ]; then
  (cd deb && { sudo -n apt-get update -qq || apt-get update -qq; } >/dev/null 2>&1
   apt-get download openssh-server openssh-client libwrap0 libwtmpdb0 >/dev/null 2>&1
   for f in *.deb; do dpkg-deb -x "$f" $R; done)
fi
K=$R/usr/bin/ssh-keygen
[ -f host_ed25519 ] || $K -q -t ed25519 -N '' -f host_ed25519 -C hark-vm-host
[ -f client_ed25519 ] || $K -q -t ed25519 -N '' -f client_ed25519 -C hark-vm-mesh
touch authorized_keys
grep -q hark-vm-selftest authorized_keys || sed 's/hark-vm-mesh$/hark-vm-selftest/' client_ed25519.pub >> authorized_keys
[ -n "$MESH_PEER_KEYS" ] && printf '%s\n' "$MESH_PEER_KEYS" | while read -r k; do [ -n "$k" ] && ! grep -qF "$k" authorized_keys && echo "$k" >> authorized_keys; done
chmod 600 authorized_keys client_ed25519 host_ed25519
cat > sshd_config <<EOF
Port 2222
ListenAddress 127.0.0.1
HostKey $D/host_ed25519
PidFile $D/sshd.pid
AuthorizedKeysFile $D/authorized_keys
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
StrictModes no
UsePAM no
SshdSessionPath $R/usr/lib/openssh/sshd-session
SshdAuthPath $R/usr/lib/openssh/sshd-auth
EOF
pgrep -f "sshd -f sshd_config" >/dev/null || $R/usr/sbin/sshd -f sshd_config -E sshd.log
: > pg.log
timeout "${1:-1100}" $R/usr/bin/ssh -F /dev/null -tt -p 443 -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
  -R0:127.0.0.1:2222 tcp@a.pinggy.io > pg.log 2>&1 < /dev/null &
for i in $(seq 1 20); do EP=$(grep -aoE "tcp://[a-z0-9.-]+:[0-9]+" pg.log | head -1); [ -n "$EP" ] && break; sleep 1; done
echo "ENDPOINT ${EP:-none} user=$(id -un) host_fp=$($K -lf host_ed25519.pub | awk '{print $2}')"
echo "CLIENT_PUB $(cat client_ed25519.pub)"
[ "${NO_WAIT:-0}" = 1 ] || wait
