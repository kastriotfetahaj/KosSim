locals {
  team_names = [for i in range(var.team_count) : "team${i + 1}"]

  service_names = ["svc1", "svc2", "svc3", "svc4", "svc5"]

  service_port_map = {
    for idx, name in local.service_names :
    name => var.team_service_base_port + idx + 1
  }

  service_port_map_string = join(",", [
    for name in local.service_names :
    "${name}=${local.service_port_map[name]}"
  ])

  team_host_map = {
    for idx, name in local.team_names :
    name => cidrhost(var.private_cidr, 100 + idx)
  }

  team_host_map_string = join(",", [
    for name in local.team_names :
    "${name}=${local.team_host_map[name]}"
  ])

  teams_string = join(",", local.team_names)

  ssh_key_names = [for key in hcloud_ssh_key.this : key.name]
}

resource "hcloud_ssh_key" "this" {
  for_each = {
    for idx, key in var.ssh_public_keys :
    idx => key
  }
  name       = "${var.competition_name}-ssh-${each.key}"
  public_key = each.value
}

resource "hcloud_network" "ctf" {
  name     = "${var.competition_name}-net"
  ip_range = var.private_cidr
}

resource "hcloud_network_subnet" "ctf" {
  type         = "cloud"
  network_id   = hcloud_network.ctf.id
  network_zone = var.network_zone
  ip_range     = var.private_cidr
}

resource "hcloud_firewall" "ctf" {
  name = "${var.competition_name}-fw"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.admin_ssh_cidrs
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = tostring(var.control_api_port)
    source_ips = var.admin_ssh_cidrs
  }

  rule {
    direction  = "in"
    protocol   = "udp"
    port       = tostring(var.vpn_udp_port)
    source_ips = var.vpn_allowed_cidrs
  }

  rule {
    direction  = "in"
    protocol   = "icmp"
    source_ips = [var.private_cidr]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "1-65535"
    source_ips = [var.private_cidr]
  }

  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "1-65535"
    source_ips = [var.private_cidr]
  }
}

resource "hcloud_server" "control" {
  name        = "${var.competition_name}-control"
  image       = var.image
  server_type = var.control_server_type
  location    = var.location
  ssh_keys    = local.ssh_key_names

  user_data = templatefile("${path.module}/templates/cloud-init-control.tftpl", {
    repo_url             = var.repo_url
    repo_ref             = var.repo_ref
    postgres_password    = var.postgres_password
    service_push_secret  = var.service_push_secret
    secret_flag_key      = var.secret_flag_key
    admin_password       = var.admin_password
    admin_session_secret = var.admin_session_secret
    game_admin_token     = var.game_admin_token
    teams_string         = local.teams_string
    service_names        = join(",", local.service_names)
    team_host_map_string = local.team_host_map_string
    service_port_map     = local.service_port_map_string
    nop_host             = cidrhost(var.private_cidr, 20)
    control_api_port     = var.control_api_port
    default_service_port = var.team_service_base_port + 1
    competition_name     = var.competition_name
  })
}

resource "hcloud_server_network" "control" {
  server_id  = hcloud_server.control.id
  network_id = hcloud_network.ctf.id
  ip         = cidrhost(var.private_cidr, 10)
}

resource "hcloud_server" "nop" {
  name        = "${var.competition_name}-nop"
  image       = var.image
  server_type = var.nop_server_type
  location    = var.location
  ssh_keys    = local.ssh_key_names

  user_data = templatefile("${path.module}/templates/cloud-init-nop.tftpl", {
    repo_url            = var.repo_url
    repo_ref            = var.repo_ref
    service_push_secret = var.service_push_secret
    nop_team_name       = "nop"
    nop_service_1_port  = var.nop_service_base_port + 1
    nop_service_2_port  = var.nop_service_base_port + 2
    nop_service_3_port  = var.nop_service_base_port + 3
    nop_service_4_port  = var.nop_service_base_port + 4
    nop_service_5_port  = var.nop_service_base_port + 5
    competition_name    = var.competition_name
  })
}

resource "hcloud_server_network" "nop" {
  server_id  = hcloud_server.nop.id
  network_id = hcloud_network.ctf.id
  ip         = cidrhost(var.private_cidr, 20)
}

resource "hcloud_server" "vpn" {
  name        = "${var.competition_name}-vpn"
  image       = var.image
  server_type = var.vpn_server_type
  location    = var.location
  ssh_keys    = local.ssh_key_names

  user_data = templatefile("${path.module}/templates/cloud-init-vpn.tftpl", {
    competition_name   = var.competition_name
    vpn_udp_port       = var.vpn_udp_port
    vpn_client_cidr    = var.vpn_client_cidr
    private_cidr       = var.private_cidr
    team_count         = var.team_count
    vpn_users_per_team = var.vpn_users_per_team
  })
}

resource "hcloud_server_network" "vpn" {
  server_id  = hcloud_server.vpn.id
  network_id = hcloud_network.ctf.id
  ip         = cidrhost(var.private_cidr, 30)
}

resource "hcloud_server" "team" {
  count = var.team_count

  name        = "${var.competition_name}-${local.team_names[count.index]}"
  image       = var.image
  server_type = var.team_server_type
  location    = var.location
  ssh_keys    = local.ssh_key_names

  user_data = templatefile("${path.module}/templates/cloud-init-team.tftpl", {
    repo_url            = var.repo_url
    repo_ref            = var.repo_ref
    service_push_secret = var.service_push_secret
    team_name           = local.team_names[count.index]
    nat_gateway_port    = var.team_nat_base_port + count.index + 1
    service_1_port      = var.team_service_base_port + 1
    service_2_port      = var.team_service_base_port + 2
    service_3_port      = var.team_service_base_port + 3
    service_4_port      = var.team_service_base_port + 4
    service_5_port      = var.team_service_base_port + 5
    competition_name    = var.competition_name
  })
}

resource "hcloud_server_network" "team" {
  count = var.team_count

  server_id  = hcloud_server.team[count.index].id
  network_id = hcloud_network.ctf.id
  ip         = local.team_host_map[local.team_names[count.index]]
}

resource "hcloud_firewall_attachment" "control" {
  firewall_id = hcloud_firewall.ctf.id
  server_ids  = [hcloud_server.control.id]
}

resource "hcloud_firewall_attachment" "nop" {
  firewall_id = hcloud_firewall.ctf.id
  server_ids  = [hcloud_server.nop.id]
}

resource "hcloud_firewall_attachment" "teams" {
  count = var.team_count

  firewall_id = hcloud_firewall.ctf.id
  server_ids  = [hcloud_server.team[count.index].id]
}

resource "hcloud_firewall_attachment" "vpn" {
  firewall_id = hcloud_firewall.ctf.id
  server_ids  = [hcloud_server.vpn.id]
}
