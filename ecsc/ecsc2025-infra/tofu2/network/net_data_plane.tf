resource "openstack_networking_network_v2" "data_plane" {
  name = "${var.ctf_name}-data-plane"
}

resource "openstack_networking_subnet_v2" "data_plane" {
  network_id      = openstack_networking_network_v2.data_plane.id
  name            = "${var.ctf_name}-data-plane"
  cidr            = "10.232.${var.network_index}.0/24"
  enable_dhcp     = false
  dns_nameservers = []
  no_gateway      = true
}

resource "openstack_networking_port_v2" "data_plane_router_team" {
  count          = var.num_routers_team
  name           = "${var.ctf_name}-data-plane-router-team-${count.index + 1}"
  network_id     = openstack_networking_network_v2.data_plane.id
  admin_state_up = true
  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.data_plane.id
    ip_address = "10.232.${var.network_index}.${11 + count.index}"
  }
}

resource "openstack_networking_port_v2" "data_plane_router_infra" {
  count          = var.num_routers_infra
  name           = "${var.ctf_name}-data-plane-router-infra-${count.index + 1}"
  network_id     = openstack_networking_network_v2.data_plane.id
  admin_state_up = true
  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.data_plane.id
    ip_address = "10.232.${var.network_index}.${254 - count.index}"
  }
}

resource "openstack_networking_port_v2" "data_plane_worker" {
  count          = var.num_workers
  name           = "${var.ctf_name}-data-plane-worker-${count.index + 1}"
  network_id     = openstack_networking_network_v2.data_plane.id
  admin_state_up = true
  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.data_plane.id
    ip_address = "10.232.${var.network_index}.${101 + count.index}"
  }
}
