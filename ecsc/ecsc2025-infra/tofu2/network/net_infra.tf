resource "openstack_networking_network_v2" "infra" {
  name = "${var.ctf_name}-infra"
}

resource "openstack_networking_subnet_v2" "infra" {
  network_id      = openstack_networking_network_v2.infra.id
  name            = "${var.ctf_name}-infra"
  cidr            = "10.${var.network_index}.251.0/24"
  enable_dhcp     = false
  dns_nameservers = []
  no_gateway      = true
}

resource "openstack_networking_port_v2" "infra_router_infra" {
  count          = var.num_routers_infra
  name           = "${var.ctf_name}-infra-router-infra-${count.index + 1}"
  network_id     = openstack_networking_network_v2.infra.id
  admin_state_up = true
  # Infra routers send return traffic from vulnboxes
  port_security_enabled = false

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.infra.id
    ip_address = "10.${var.network_index}.251.${254 - count.index}"
  }
}

resource "openstack_networking_port_v2" "infra_gameserver" {
  count          = var.num_gameservers
  name           = "${var.ctf_name}-infra-gameserver-${count.index + 1}"
  network_id     = openstack_networking_network_v2.infra.id
  admin_state_up = true

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.infra.id
    ip_address = "10.${var.network_index}.251.${2 + count.index}"
  }
}

resource "openstack_networking_port_v2" "infra_checker" {
  count          = var.num_checkers
  name           = "${var.ctf_name}-infra-checkers-${count.index + 1}"
  network_id     = openstack_networking_network_v2.infra.id
  admin_state_up = true

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.infra.id
    ip_address = "10.${var.network_index}.251.${16 + count.index}"
  }
}

resource "openstack_networking_port_v2" "infra_observer" {
  count          = var.num_observers
  name           = "${var.ctf_name}-infra-observer-${count.index + 1}"
  network_id     = openstack_networking_network_v2.infra.id
  admin_state_up = true

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.infra.id
    ip_address = "10.${var.network_index}.251.${31 - count.index}"
  }
}
