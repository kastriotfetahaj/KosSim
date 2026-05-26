terraform {
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "3.0.0"
    }
  }
}

locals {
  team_vol_names = var.pcap_volumes.size == 0 ? [] : [
    for i in range(var.num_routers_team) : "router-${i + 1}"
  ]
  infra_vol_names = var.pcap_volumes.size == 0 ? [] : [
    for i in range(var.num_routers_infra) : "router-infra-${i + 1}"
  ]
  effective_sizes = {
    for name in concat(local.team_vol_names, local.infra_vol_names) :
    name => lookup(var.pcap_volumes.overrides, name, var.pcap_volumes.size)
  }
}

resource "openstack_blockstorage_volume_v3" "pcaps_team" {
  count                = length(local.team_vol_names)
  name                 = "${var.ctf_name}-${local.team_vol_names[count.index]}"
  size                 = local.effective_sizes[local.team_vol_names[count.index]]
  volume_type          = var.pcap_volumes.type
  enable_online_resize = true
}

resource "openstack_blockstorage_volume_v3" "pcaps_infra" {
  count                = length(local.infra_vol_names)
  name                 = "${var.ctf_name}-${local.infra_vol_names[count.index]}"
  size                 = local.effective_sizes[local.infra_vol_names[count.index]]
  volume_type          = var.pcap_volumes.type
  enable_online_resize = true
}
