#!/bin/bash
# NMarketing: remote access to the processing servers - the VPS side (idempotent). 1405/08/19.
#   * user nmtunnel: no shell, no password; each node's key may only open ITS port on 127.0.0.1 (reverse tunnel, -R);
#     the keys are written by the site (apps/compute/remote.py) when a node runs Setup-Remote.bat
#   * /root/.ssh/nm_node_admin: the key the site and nm-node use to log in to the nodes through their tunnel
#   * /usr/local/bin/nm-node: the command line for the nodes
# Undo: rm /etc/ssh/sshd_config.d/60-nm-tunnel.conf; systemctl reload ssh; userdel -r nmtunnel; rm /usr/local/bin/nm-node
set -euo pipefail
ROOT=/var/www/NM/upmarket
U=nmtunnel
H=/var/lib/nmtunnel

id -u "$U" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$H" --shell /usr/sbin/nologin "$U"
passwd -l "$U" >/dev/null 2>&1 || true
install -d -m 700 -o "$U" -g "$U" "$H/.ssh"
[ -f "$H/.ssh/authorized_keys" ] || install -m 600 -o "$U" -g "$U" /dev/null "$H/.ssh/authorized_keys"

[ -f /root/.ssh/nm_node_admin ] || ssh-keygen -q -t ed25519 -N "" -C "nm-vps-admin@$(hostname)" -f /root/.ssh/nm_node_admin
touch /root/.ssh/nm_nodes_known_hosts && chmod 600 /root/.ssh/nm_nodes_known_hosts

CONF=/etc/ssh/sshd_config.d/60-nm-tunnel.conf
cat > "$CONF.new" <<'EOF'
# NMarketing processing-node tunnels (deploy/nm/remote-access-setup.sh). The per-key options in
# /var/lib/nmtunnel/.ssh/authorized_keys (restrict,port-forwarding,permitlisten="127.0.0.1:<port>") narrow it further.
Match User nmtunnel
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AllowTcpForwarding remote
    AllowStreamLocalForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitUserRC no
    PermitTTY no
    GatewayPorts no
    ForceCommand /bin/false
EOF
if ! cmp -s "$CONF.new" "$CONF" 2>/dev/null; then
  mv "$CONF.new" "$CONF"
  sshd -t
  systemctl reload ssh
  echo "sshd: $CONF installed and reloaded"
else
  rm -f "$CONF.new"
fi

install -m 755 "$ROOT/deploy/nm/nm-node" /usr/local/bin/nm-node
mkdir -p "$ROOT/data/remote" && chmod 700 "$ROOT/data/remote"
echo "remote access ready: user $U, key /root/.ssh/nm_node_admin, command nm-node"
