resource "openstack_networking_network_v2" "team_cloud" {
  count = var.num_routers_team
  name  = "${var.ctf_name}-team-cloud-${count.index + 1}"
}

resource "openstack_networking_subnet_v2" "team_cloud" {
  count           = var.num_routers_team
  network_id      = openstack_networking_network_v2.team_cloud[count.index].id
  name            = "${var.ctf_name}-team-cloud-${count.index + 1}"
  cidr            = "10.${var.network_index + 1}.${count.index + 1}.0/24"
  dns_nameservers = ["1.1.1.1", "8.8.8.8"]
  enable_dhcp     = true
  allocation_pool {
    start = "10.${var.network_index + 1}.${count.index + 1}.10"
    end   = "10.${var.network_index + 1}.${count.index + 1}.250"
  }
  gateway_ip = "10.${var.network_index + 1}.${count.index + 1}.254"
}

resource "openstack_networking_port_v2" "router_team_cloud" {
  count                 = var.num_routers_team
  name                  = "${var.ctf_name}-team-cloud-router-team-${count.index + 1}"
  network_id            = openstack_networking_network_v2.team_cloud[count.index].id
  admin_state_up        = true
  port_security_enabled = false

  fixed_ip {
    subnet_id  = openstack_networking_subnet_v2.team_cloud[count.index].id
    ip_address = "10.${var.network_index + 1}.${count.index + 1}.254"
  }
}
