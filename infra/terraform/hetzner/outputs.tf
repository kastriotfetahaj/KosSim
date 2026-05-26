output "control_public_ipv4" {
  value       = hcloud_server.control.ipv4_address
  description = "Control plane public IPv4 (scoreboard + submit API)."
}

output "control_private_ipv4" {
  value       = hcloud_server_network.control.ip
  description = "Control plane private IPv4."
}

output "nop_private_ipv4" {
  value       = hcloud_server_network.nop.ip
  description = "NOP host private IPv4."
}

output "team_private_ipv4s" {
  value = {
    for idx, name in local.team_names :
    name => hcloud_server_network.team[idx].ip
  }
  description = "Team host private IPv4 mapping."
}

output "team_public_ipv4s" {
  value = {
    for idx, name in local.team_names :
    name => hcloud_server.team[idx].ipv4_address
  }
  description = "Team host public IPv4 mapping."
}

output "vpn_public_ipv4" {
  value       = hcloud_server.vpn.ipv4_address
  description = "VPN host public IPv4."
}

output "vpn_private_ipv4" {
  value       = hcloud_server_network.vpn.ip
  description = "VPN host private IPv4."
}

output "vpn_udp_port" {
  value       = var.vpn_udp_port
  description = "VPN UDP listen port."
}

output "vpn_client_profiles_path" {
  value       = "/etc/wireguard/clients"
  description = "Path on VPN host where generated per-team client configs are stored."
}
