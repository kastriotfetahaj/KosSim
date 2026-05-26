locals {
  any_ip_type = toset(["IPv4", "IPv6"])
}

resource "openstack_networking_secgroup_v2" "ext_infra" {
  name        = "${var.ctf_name}-infra-ext-secgroup"
  description = "The basic infra security group"
}

resource "openstack_networking_secgroup_rule_v2" "allow_icmp" {
  direction         = "ingress"
  protocol          = "icmp"
  security_group_id = openstack_networking_secgroup_v2.ext_infra.id
  ethertype         = "IPv4"
}

resource "openstack_networking_secgroup_rule_v2" "allow_icmp6" {
  direction         = "ingress"
  protocol          = "ipv6-icmp"
  security_group_id = openstack_networking_secgroup_v2.ext_infra.id
  ethertype         = "IPv6"
}

resource "openstack_networking_secgroup_rule_v2" "allow_v4_ssh" {
  direction         = "ingress"
  port_range_min    = 22
  port_range_max    = 22
  protocol          = "tcp"
  security_group_id = openstack_networking_secgroup_v2.ext_infra.id

  for_each  = local.any_ip_type
  ethertype = each.value
}

resource "openstack_networking_secgroup_rule_v2" "allow_cilium" {
  direction         = "ingress"
  port_range_min    = 51871
  port_range_max    = 51871
  protocol          = "udp"
  security_group_id = openstack_networking_secgroup_v2.ext_infra.id

  for_each  = local.any_ip_type
  ethertype = each.value
}

resource "openstack_networking_secgroup_v2" "ext_router" {
  name        = "${var.ctf_name}-router-ext-secgroup"
  description = "Security group for infra routers"
}

resource "openstack_networking_secgroup_rule_v2" "allow_icmp_router" {
  direction         = "ingress"
  protocol          = "icmp"
  security_group_id = openstack_networking_secgroup_v2.ext_router.id
  ethertype         = "IPv4"
}

resource "openstack_networking_secgroup_rule_v2" "allow_icmp6_router" {
  direction         = "ingress"
  protocol          = "ipv6-icmp"
  security_group_id = openstack_networking_secgroup_v2.ext_router.id
  ethertype         = "IPv6"
}

resource "openstack_networking_secgroup_rule_v2" "allow_ssh_router" {
  direction         = "ingress"
  port_range_min    = 22
  port_range_max    = 22
  protocol          = "tcp"
  security_group_id = openstack_networking_secgroup_v2.ext_router.id
  for_each          = local.any_ip_type
  ethertype         = each.value
}

resource "openstack_networking_secgroup_rule_v2" "allow_team_wg_router" {
  direction         = "ingress"
  port_range_min    = 50000
  port_range_max    = 50250
  protocol          = "udp"
  security_group_id = openstack_networking_secgroup_v2.ext_router.id
  for_each          = local.any_ip_type
  ethertype         = each.value
}

/*resource "openstack_networking_secgroup_rule_v2" "allow_iperf" {
  direction         = "ingress"
  port_range_min    = 2111
  port_range_max    = 2112
  protocol          = "tcp"
  security_group_id = openstack_networking_secgroup_v2.ext_router.id
  for_each          = local.any_ip_type
  ethertype         = each.value
}
*/
