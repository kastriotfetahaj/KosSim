#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

NETWORK_CONFIG_FILE = "/root/.team_ip"
IP_PATTERN = [(1, 1, 10), (200, 200, 32), (1, 200, 0)]


def get_ip(team_id, suffix):
    return ".".join(
        [str(((team_id // a) % b) + c) for a, b, c in IP_PATTERN] + [str(suffix)]
    )


def query_yes_no(question, default="yes"):
    """
    Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    From http://code.activestate.com/recipes/577058/
    """
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == "":
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")


def query_options(question: str, options: list[str]) -> str:
    sys.stdout.write(question + "\n")
    for i, option in enumerate(options):
        sys.stdout.write(f"[{i}] {option}\n")
    while True:
        sys.stdout.write(f"[0-{len(options) - 1}] ")
        choice = input().strip()
        try:
            c = int(choice)
            return options[c]
        except (KeyError, ValueError):
            sys.stdout.write("Invalid choice\n")


def generate_vpn_keys():
    path = "/etc/openvpn/pki"
    if os.path.exists(os.path.join(path, "ta.key")):
        print("[.] VPN keys already present")
        return
    env = dict(os.environ.items())
    env["EASYRSA_BATCH"] = "1"
    subprocess.check_call(
        ["/usr/share/easy-rsa/easyrsa", "init-pki"], env=env, cwd="/etc/openvpn"
    )
    subprocess.check_call(
        ["/usr/share/easy-rsa/easyrsa", "build-ca", "nopass"],
        env=env,
        cwd="/etc/openvpn",
    )
    subprocess.check_call(
        ["/usr/share/easy-rsa/easyrsa", "gen-req", "server", "nopass"],
        env=env,
        cwd="/etc/openvpn",
    )
    subprocess.check_call(
        ["/usr/share/easy-rsa/easyrsa", "gen-req", "TeamMember", "nopass"],
        env=env,
        cwd="/etc/openvpn",
    )
    subprocess.check_call(
        ["/usr/share/easy-rsa/easyrsa", "sign-req", "server", "server"],
        env=env,
        cwd="/etc/openvpn",
    )
    subprocess.check_call(
        ["/usr/share/easy-rsa/easyrsa", "sign-req", "client", "TeamMember"],
        env=env,
        cwd="/etc/openvpn",
    )
    subprocess.check_call(
        ["/usr/share/easy-rsa/easyrsa", "gen-dh"], env=env, cwd="/etc/openvpn"
    )
    subprocess.check_call(["openvpn", "--genkey", "--secret", "ta.key"], cwd=path)
    print("[*] VPN keys have been generated.")


def configure_vpnserver(team_id):
    generate_vpn_keys()
    server_config = f"""
    port 1194
    proto udp
    dev tun
    
    server {get_ip(team_id, 64)} 255.255.255.192
    keepalive 10 120
    
    push "route 10.32.0.0 255.255.0.0"
    push "route 10.33.0.0 255.255.0.0"
    
    ca /etc/openvpn/pki/ca.crt
    cert /etc/openvpn/pki/issued/server.crt
    key /etc/openvpn/pki/private/server.key
    dh /etc/openvpn/pki/dh.pem
    tls-auth /etc/openvpn/pki/ta.key
    duplicate-cn
    cipher AES-128-CBC
    
    user nobody
    group nogroup
    persist-key
    persist-tun
    status openvpn-status.log
    verb 3
    explicit-exit-notify 1
    """.replace("\n\t", "\n")
    with open("/etc/openvpn/teamserver.conf", "w") as f:
        f.write(server_config)

    client_config = """
    remote TODO_YOUR_SERVER_IP 1194  # TODO PATCH HERE
    client
    dev tun
    proto udp
    nobind

    remote-cert-tls server
    cipher AES-128-CBC

    user nobody
    group nogroup
    persist-key
    persist-tun
    """.replace("\n\t", "\n")
    included_files = {
        "ca": "/etc/openvpn/pki/ca.crt",
        "cert": "/etc/openvpn/pki/issued/TeamMember.crt",
        "key": "/etc/openvpn/pki/private/TeamMember.key",
        "tls-auth": "/etc/openvpn/pki/ta.key",
    }
    for name, fname in included_files.items():
        client_config += f"\n<{name}>\n"
        with open(fname, "r") as f:
            client_config += f.read()
        client_config += f"\n</{name}>\n"
    with open("/root/team-vpn-client.conf", "w") as f:
        f.write(client_config)
    print('[.] Find your client configuration at "/root/team-vpn-client.conf". ')
    print(
        "    IMPORTANT: Update the first line with your IP, then distribute to your teammates."
    )
    subprocess.check_call(["systemctl", "start", "openvpn@teamserver"])
    subprocess.check_call(["systemctl", "enable", "openvpn@teamserver"])


def gen_wg_keypair() -> tuple[str, str]:
    privkey = subprocess.check_output(["wg", "genkey"]).decode("utf-8").strip()
    pubkey = (
        subprocess.check_output(["wg", "pubkey"], input=privkey.encode())
        .decode("utf-8")
        .strip()
    )
    return privkey, pubkey


def configure_wireguard_vpnserver(team_id: int) -> None:
    server_sk, server_pk = gen_wg_keypair()
    config = f"""
[Interface]
Address = {get_ip(team_id, 64)}/26
SaveConfig = true
ListenPort = 51820
PrivateKey = {server_sk}
"""

    for i in range(1, 65):
        client_sk, client_pk = gen_wg_keypair()
        config += f"""[Peer]
PublicKey = {client_pk}
AllowedIPs = {get_ip(team_id, 64 + i)}/32
"""
        client_config = f"""
[Interface]
PrivateKey = {client_sk}
Address = {get_ip(team_id, 64 + i)}/26

[Peer]
PublicKey = {server_pk}
AllowedIPs = 10.32.0.0/15
Endpoint = SERVER_PUBLIC_IP:51820  # TODO insert IP
PersistentKeepalive = 20
"""
        Path(f"/root/team-wireguard-client-{i}.conf").write_text(client_config)

    Path("/etc/wireguard/teamserver.conf").write_text(config)
    print(
        '[.] Find your client configuration at "/root/team-wireguard-client-XXX.conf". '
    )
    print(
        '    IMPORTANT: Replace "SERVER_PUBLIC_IP" with your IP, then distribute to your teammates.'
    )
    print("    Each config file can be used by only one player.")
    subprocess.check_call(["systemctl", "start", "wg-quick@teamserver"])
    subprocess.check_call(["systemctl", "enable", "wg-quick@teamserver"])


def main():
    print("")
    while True:
        x = input("Please enter your Team ID: ")
        if not x:
            break
        try:
            team_id = int(x)
        except ValueError:
            print("Invalid ID.")
            continue
        if query_yes_no(
            "Do you want a VPN server (OpenVPN or Wireguard) for your teammates to connect to?"
        ):
            opt = query_options("Which VPN type?", ["(none)", "OpenVPN", "Wireguard"])
            if opt == "OpenVPN":
                print("[.]  Configuring OpenVPN server ...")
                configure_vpnserver(team_id)
                print("[*]  OpenVPN active.")
            elif opt == "Wireguard":
                print("[.]  Configuring Wireguard VPN server ...")
                configure_wireguard_vpnserver(team_id)
                print("[*]  Wireguard VPN active.")
        print("")
        print(f"Your team range:  {get_ip(team_id, 0)}/24")
        print(f"Your local range: {get_ip(team_id, 0)}/25")
        print(f"Your router IP:   {get_ip(team_id, 1)}")
        print(f"Your vulnbox IP:  {get_ip(team_id, 2)}")
        print(f"Your testbox IP:  {get_ip(team_id, 3)}")
        print(f"Your teammates:   {get_ip(team_id, 64)} - {get_ip(team_id, 253)}")
        print("")
        print("Configuration finished.")
        with open(NETWORK_CONFIG_FILE, "w") as f:
            f.write(get_ip(team_id, ""))
        break
    print("")


if __name__ == "__main__":
    main()
