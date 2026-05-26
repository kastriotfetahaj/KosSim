data "openstack_networking_network_v2" "ext_net" {
  name = "Ext-Net"
}

resource "openstack_networking_port_v2" "ext_router_team" {
  count              = var.num_routers_team
  name               = "${var.ctf_name}-ext-router-team-${count.index + 1}"
  network_id         = data.openstack_networking_network_v2.ext_net.id
  security_group_ids = [openstack_networking_secgroup_v2.ext_router.id]
  admin_state_up     = true
}

resource "openstack_networking_port_v2" "ext_router_infra" {
  count              = var.num_routers_infra
  name               = "${var.ctf_name}-ext-router-infra-${count.index + 1}"
  network_id         = data.openstack_networking_network_v2.ext_net.id
  security_group_ids = [openstack_networking_secgroup_v2.ext_router.id]
  admin_state_up     = true
}

resource "openstack_networking_port_v2" "ext_worker" {
  count              = var.num_workers
  name               = "${var.ctf_name}-ext-worker-${count.index + 1}"
  network_id         = data.openstack_networking_network_v2.ext_net.id
  security_group_ids = [openstack_networking_secgroup_v2.ext_infra.id]
  admin_state_up     = true
}

resource "openstack_networking_port_v2" "ext_gameserver" {
  count              = var.num_gameservers
  name               = "${var.ctf_name}-ext-gameserver-${count.index + 1}"
  network_id         = data.openstack_networking_network_v2.ext_net.id
  security_group_ids = [openstack_networking_secgroup_v2.ext_infra.id]
  admin_state_up     = true
}

resource "openstack_networking_port_v2" "ext_checker" {
  count              = var.num_checkers
  name               = "${var.ctf_name}-ext-checkers-${count.index + 1}"
  network_id         = data.openstack_networking_network_v2.ext_net.id
  security_group_ids = [openstack_networking_secgroup_v2.ext_infra.id]
  admin_state_up     = true
}

resource "openstack_networking_port_v2" "ext_observer" {
  count              = var.num_observers
  name               = "${var.ctf_name}-ext-observer-${count.index + 1}"
  network_id         = data.openstack_networking_network_v2.ext_net.id
  security_group_ids = [openstack_networking_secgroup_v2.ext_infra.id]
  admin_state_up     = true
}
