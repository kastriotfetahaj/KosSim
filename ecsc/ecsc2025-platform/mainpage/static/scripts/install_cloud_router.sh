#!/usr/bin/env bash

set -e


# Download VPN setup script if necessary
test -f install_cloud_router_vpn.py || wget 'https://ctf.saarland/static/scripts/install_cloud_router_vpn.py'


# Install required and useful packages
echo "[1] Install required and useful packages"
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get upgrade -y
apt-get install -y sudo wget python3-minimal htop nano \
        net-tools bash-completion screen vim man lsof tcpdump \
        iptables-persistent openvpn wireguard wireguard-tools easy-rsa bmon iftop iptraf nload pktstat
ln -s /usr/bin/nload /usr/sbin/iftop /usr/sbin/iptraf /usr/bin/bmon /usr/sbin/pktstat /root/


# Enable IP forwarding
echo "[2] Enable IP forwarding"
sysctl -w net.ipv4.ip_forward=1
echo 'net.ipv4.ip_forward = 1' >> /etc/sysctl.conf


# Default firewall
echo "[3] Configure iptables"
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables-save > /etc/iptables/rules.v4


# Patch openvpn service - faster reconnect
echo "[4] Patch OpenVPN service"
mkdir -p /etc/systemd/system/openvpn-client@.service.d
mkdir -p /etc/systemd/system/openvpn@.service.d
cat > /etc/systemd/system/openvpn-client@.service.d/override.conf <<'EOF'
[Service]
Restart=always
RestartSec=5
EOF
cat > /etc/systemd/system/openvpn@.service.d/override.conf <<'EOF'
[Service]
Restart=always
RestartSec=5
EOF


# Setup VPN?
echo "[5] Setup VPN ..."
python3 install_cloud_router_vpn.py


echo "[*] COMPLETED!"
